"""FX6 (ILME-FX6) firmware 6.02: run one of the two READ-ONLY helper libraries and save what it reports, or one write step.

  python fx6_run.py check --dry-run | --selftest
  python fx6_run.py dump  --dry-run | --selftest
  python fx6_run.py check --go --firmware-shown 6.02
  python fx6_run.py dump  --go --firmware-shown 6.02 [--clear-result SHA256]

  check   identity of the camera's software and what every site of the open-gate designs holds now: READY / NOT READY
          (the screen step's words are reported as well, not counted: it is optional)
  dump    the same, plus kernel and memory facts, the coprocessor's logs and some of its tables (sensor registers, stored
          records, the scaler's state, the drive mode the camera ran before the session, the display words, the output-plane
          memory table). This is the debug dump testers send back.

Both read-only libraries only read. Each creates one file, its result, on the camera's RAM disk; this script fetches it. The
library is written to the camera's service partition, loaded once, and deleted again in the same session.

The FX6 counterpart of fx3_run.py (the FX3 kit, whose open-gate state works on two FX3s), made from it on 2026-11-26 with this
camera's libraries, pins and result reader. The FX6 6.02 coprocessor software carries the FX3 7.02's imager code and tables at
other addresses (modding/FX6_PORT.md). Nothing here can send a memory write unless a write step is named with --writes-memory.
"""
import argparse
import json
import platform
import re
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "CT1_usb_first_contact"))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "helper"))
sys.path.insert(0, str(HERE / "helper_fx6"))
import ct1_common as c  # noqa: E402
import ct6_level1_run as R  # noqa: E402

FIRMWARE, MODEL, BUILD = "6.02", "ILME-FX6", "fx6_602"
LABELS = ("fx6read_v1", "fx6read_v2")           # the read-only helper versions this runner reads
S3 = HERE / "helper_fx6"                        # this kit's folder (the name S3 is kept from s3_run.py)
# fx6read_v2 (2026-11-26, after the testers' first runs): + the output-plane memory words (11 sites), the table's pages in the dump, /log/cp
PINS = {"check": ("libJit_fx6_check.so", "644b463c26b2fdb380f700a6a3cdd6df102f48218d3a53df02ade93abad59e0b"),
        "dump": ("libJit_fx6_dump.so", "6bfc25e91676cc4e3c0c704130dc2fd17b0b5d3af43bf892c0e8a4fe8efb09d3")}
LEVELS = {"check": 101, "dump": 102}              # numbers outside the A7 IV runner's own levels: none of its level-specific code runs
# THE WRITE STEPS. Each is one library built from the A7 IV helper's write code with this camera's tables (helper_fx6/build_fx6_write.sh).
# They change the running camera's memory until a cold boot. They are run through fx6_apply.py, never by a launcher of the read-only kit,
# and the libraries are not in the published kit unless it was published with --include-write.
WRITE_STEPS = {
    # The output-plane memory step (added 2026-11-26 after the testers' first runs; build/build_dmm_fx6.py): the level 16/17 code with words of
    # the camera's run-time copy of DmmCfg.bin. The FX6 fills an output plane at 1.5 bytes per pixel, so its 13,271,040-byte planes hold
    # 3840 x 2304; without this step the output-size step L16 stops clips being written (repo issue 1) or the last 256 rows repeat (issue 2).
    # D16 = the ten words a tester ran on an FX6 (repo issue 2, Mininoob). R16 = a variant that retags the HD layout's plane instead of
    # enlarging it (no refused request in the FX6's own allocator; not run). D17 puts back the words of either.
    "D16": ("libJit_fx6_D16.so", "32a2bbc5125603c9beaa56614f48d0d928074dd603fbc3dade0ce486e60cda79", "apply the output-plane memory words dmm7slot_fx6_v1 (ten words of the DmmCfg table: seven 4K planes of 14,745,600 bytes, the eighth out of the pool, the HD layout's plane enlarged; the words a tester ran on an FX6)"),
    "R16": ("libJit_fx6_R16.so", "28f182217719eef43ef0abffcd3c97ec632570657a8ef060fb46c9e72a6a3f29", "apply the output-plane memory words, variant dmm7slot_fx6_v2 (ten words: seven 4K planes of 14,745,600 bytes, the eighth and the HD layout's plane out of the pool; NOT run on a camera)"),
    "D17": ("libJit_fx6_D17.so", "762ca5ac5a6eadc7b143924d99e8566635e30188e8547a76919bf4b0e583cef7", "put back the output-plane memory words (dmm7slot_fx6_v1 or _v2)"),
    "L5": ("libJit_fx6_L5.so", "5ed7dfb6d44d4f1fd3c750fde5302ac3f34aac0c433d1fc2ca5a86251a6047c5", "apply the sensor-side design ogsq_fx6_v1 (sensor cells, two records, the stored record; the FX3's working ogsq_fx3_v1)"),
    "L6": ("libJit_fx6_L6.so", "102864a6a5538be16c22f54edd5aa7c42b674032bef5d488fa4578716db07d7e", "put back the sensor-side design ogsq_fx6_v1"),
    "L16": ("libJit_fx6_L16.so", "2c405ab72a3f80a2e3305cdcb54b9939b3d4f64f3aed850228cf998db3decd1f", "apply the output size outsz2560_fx6_v1 (one word)"),
    "L17": ("libJit_fx6_L17.so", "08289301e12b72f4743ffe16dda39233e15de0ae21013aa99e9bc4d34d08f464", "put back the output size outsz2560_fx6_v1"),
    # L19/L20: ogfile2560_xavc_fx6_v2 = v1 (build/build_ogfile_fx6.py, emulated on the FX6's own code by build/emu_ogfile_fx6.py: XAVC-I QFHD and
    # XAVC-L QFHD 4:2:0 8-bit at 23.98p and 25p; XAVC-L QFHD 4:2:2 10-bit left out, its codec memory at 2560 rows exceeds the FX6's blocks) + the MXF
    # picture descriptor's height and aspect (build/build_ogfile_fx6_meta.py, emulated by build/emu_mxf_meta_fx6.py): QFHD files say 3840x2560, 3:2.
    # Sony's XML is unchanged. L20 puts back either version. N19 = v1 byte for byte (apply --no-meta); its own put back (N20) is not shipped: on a
    # camera holding v2 it would leave the header sites (as on the FX3).
    "L19": ("libJit_fx6_L19.so", "bc85507f04dcc8836290f601a14103a0db2b5607340b4b08d46ec07f39cebad9", "apply the encoder side ogfile2560_xavc_fx6_v2 (XAVC-I QFHD and XAVC-L QFHD 4:2:0 8-bit at 23.98p and 25p: 47 av-cam.bin + 2 libmpr.so sites, and the MXF header says 3840x2560 3:2: 4 more; NOT XAVC-L 4:2:2 10-bit)"),
    "L20": ("libJit_fx6_L20.so", "b225df8a191e7bd2758d7c5ebf0b25eb21f2e7c76b235c0e0919d78f4812cc72", "put back the encoder side ogfile2560_xavc_fx6_v2 (or v1)"),
    "N19": ("libJit_fx6_N19.so", "7033d38a986f413bfd35791e485e515499c5759fb154a9c693c12ca063d3fb01", "apply the encoder side without the MXF header sites, ogfile2560_xavc_fx6_v1 (the MXF header keeps saying 3840x2160, 16:9)"),
    # The LCD step (optional, on top of the open-gate state): the same level 16/17 code with the LCD words (lcd32_fx6_v1, build/build_lcd_fx6.py).
    "S16": ("libJit_fx6_S16.so", "2d775ea9843da83d267b48fb8462fb9d38a751b6266f056ec73f0f0f7603d442", "apply the LCD words lcd32_fx6_v1 (the 3:2 picture pillarboxed on the 16:9 LCD, and LCD Monitor De-Squeeze ratios for a 3:2 picture: 8 words)"),
    "S17": ("libJit_fx6_S17.so", "d336fcd1d7bfbc7f879409978c94c43c0cf6428b18de3b0721feefca7545c999", "put back the LCD words lcd32_fx6_v1"),
}
PINS.update({k: v[:2] for k, v in WRITE_STEPS.items()})
LEVELS.update({k: {"L": 200, "S": 300, "N": 500, "D": 600, "R": 700}[k[0]] + int(k[1:]) for k in WRITE_STEPS})
# Lines every result carries on this camera and that mean nothing: the helper's file list names folders (/proc/driver/pcie/*, /log/cp), which
# read as error -21, and log files longer than the copy's limit.
BENIGN = re.compile(r"^!! (read failed -21|truncated at \d+ bytes)$")
WHICH = "check"
# Libraries this kit published before and no longer runs. With PINS they are the files a run may delete from the camera's service partition
# when an earlier session left one behind (R.KNOWN_LIBS, as in fx3_run.py: a cut-off session leaves its library on that partition, which is
# flash, so it is still there after a cold boot and every later step, having another library, refused to go on).
EARLIER_LIBS = {
    "352d21b7a5458a3e4abadef6b833d2f9650f52d7d52a9835af3ec9ca3c4e656a": "the first kit's read-only check (fx6read_v1)",
    "fdda69f802dc21453681117e0e521e0d755207f97d81bd35fc44cb18b4f0868a": "the first kit's read-only dump (fx6read_v1)",
}
EXTRA_LIBS = {}                                   # --remove-library: one more file, named by its SHA-256 on the command line


def known_libs():
    out = {sha: "this kit's %s library (%s)" % ("read-only " + k if k in ("check", "dump") else "step " + k, name) for k, (name, sha) in PINS.items()}
    out.update(EARLIER_LIBS)
    out.update(EXTRA_LIBS)
    return out


def write_result(data):
    """The facts of a write step's result (the A7 IV helper's report format)."""
    import hashlib
    text = data.decode("utf8", "replace")
    lines = text.split("\n")
    pick = lambda start: next((ln for ln in lines if ln.startswith(start)), None)
    outcome = ("UNDO INCOMPLETE" if pick("!! UNDO INCOMPLETE") or pick("UNDO INCOMPLETE") else "DONE" if pick("DONE: ") else "NOTHING TO DO" if pick("NOTHING TO DO") else
               "NOT DONE (everything put back)" if pick("NOT DONE: ") else "NOTHING WRITTEN" if any("nothing is written" in ln for ln in lines) else "UNKNOWN")
    problems = [ln for ln in lines if ln.startswith("!!") and not BENIGN.match(ln)]
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "header_ok": lines[0].startswith("readcheck 1 level %s" % WHICH[1:]),
            "euid": "see the result", "sections": [ln for ln in lines if ln.startswith("== ")], "problems": len(problems),
            "complete": any(ln.startswith("== done") for ln in lines[-3:]),
            "s3": {"step": WHICH, "what": WRITE_STEPS[WHICH][2], "outcome": outcome, "ok": outcome in ("DONE", "NOTHING TO DO"),
                   "outcome_line": pick("DONE: ") or pick("NOTHING TO DO") or pick("NOT DONE: ") or pick("!! UNDO INCOMPLETE") or pick("UNDO INCOMPLETE"), "problem_lines": problems}}


def reference():
    return json.loads((S3 / "fx6_reference.json").read_text(encoding="utf8"))


def expected():
    return json.loads((S3 / "fx6_expected.json").read_text(encoding="utf8"))


# ------------------------------------------------------------ reading a result

def check_result(data):
    """The facts of a result file. Keys the A7 IV runner prints, plus this helper's own under "s3"."""
    if WHICH in WRITE_STEPS:
        return write_result(data)
    text = data.decode("utf8", "replace")
    lines = text.split("\n")
    head = lines[0] if lines else ""
    count = lambda pat: sum(1 for ln in lines if re.search(pat, ln))
    verdict = next((ln for ln in lines if ln.startswith("VERDICT ")), "no verdict line")
    pages = {}
    for ln in lines:
        if ln.startswith("cppage "):
            _, name, addr, hx = ln.split(" ", 3)
            pages[int(addr, 16)] = (name, bytes.fromhex(hx.strip()))
    sites = []
    for ln in lines:
        m = re.match(r"site (\S+) (0x[0-9a-f]+) len (\d+)(?: bytes (?:differing from stock )?(\S+))?  (STOCK|TARGET|OTHER.*|NOT READ)$", ln)
        if m:
            sites.append({"name": m.group(1), "address": m.group(2), "length": int(m.group(3)), "shown": m.group(4), "state": m.group(5)})
    s3 = {"header": head, "verdict": verdict, "ready": verdict.startswith("VERDICT READY"),
          "identity_same": count(r"SAME as the 6\.02 update$"), "identity_differs": count(r"DIFFERS from the 6\.02 update$"),
          "coprocessor_sites": sites, "libmpr_sites": [ln for ln in lines if ln.startswith("lm ")],
          "avcam_stock": count(r"^av .*  STOCK$"), "avcam_target": count(r"^av .*  TARGET$"), "avcam_other": count(r"^av .*  OTHER$"),
          "avcam_guards": [ln for ln in lines if ln.startswith("guard ")], "problem_lines": [ln for ln in lines if ln.startswith("!!") and not BENIGN.match(ln)],
          "expected_lines": sum(1 for ln in lines if BENIGN.match(ln)),
          "pages": len(pages)}
    cmd = re.search(r"== file /proc/cmdline\n(.*?)\n== end", text, re.S)
    ver = re.search(r"== file /proc/version\n(.*?)\n== end", text, re.S)
    s3["kernel_command_line"], s3["kernel_version"] = (cmd.group(1).strip() if cmd else None), (ver.group(1).strip() if ver else None)
    if pages:
        s3["decoded"] = decode_pages(pages)
    import hashlib
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "header_ok": head.startswith("fx6read ") and "ILME-FX6 6.02" in head, "euid": "not read",
            "sections": [ln for ln in lines if ln.startswith("== ")], "problems": len(s3["problem_lines"]), "complete": "== done" in lines[-3:],
            "s3": s3, "_pages": pages}


def decode_pages(pages):
    """What the dump's coprocessor pages say, set against the firmware file's tables (fx6_reference.json)."""
    ref, out = reference(), {}

    def mem(addr, n):
        b = bytearray()
        while n:
            page = pages.get(addr & ~0xFFF)
            if page is None:
                return None
            take = min(n, 4096 - (addr & 0xFFF))
            b += page[1][addr & 0xFFF:(addr & 0xFFF) + take]
            addr, n = addr + take, n - take
        return bytes(b)

    # the sensor register shadow against each column of the register matrix (the FX6's: the FX3's 489 rows in order, plus 7 all-zero rows)
    rows = [(a, bytes.fromhex(h)) for a, h in ref["matrix"]]
    shadow = [(a, mem(a, 1)) for a, _ in rows]
    if all(v is not None for _, v in shadow):
        score = [sum(1 for (a, cols), (_, v) in zip(rows, shadow) if cols[k] == v[0]) for k in range(12)]
        best = max(range(12), key=lambda k: score[k])
        users = [ref["mode_ids"][i] for i, (col, _) in enumerate(ref["column_map"]) if col == best]
        win = ref["window_rows"]
        out["sensor_registers"] = {"rows": len(rows), "rows_equal_per_column": score, "closest_column": best, "modes_using_it": users,
                                   "rows_differing_from_it": [[i, hex(a), cols[best], v[0]] for i, ((a, cols), (_, v)) in enumerate(zip(rows, shadow)) if cols[best] != v[0]][:64],
                                   "window_rows": [shadow[i][1][0] for i in win]}
    m0 = int(ref["matrix_address"], 16)
    got = mem(m0, 16 * len(rows)) if (m0 & ~0xFFF) in pages else None
    if got is not None:
        want = b"".join(struct.pack("<I", a) + cols for a, cols in rows)
        out["matrix_equals_file"] = got == want
    r0, size = int(ref["records_address"], 16), ref["record_size"]
    recs = {}
    for i, mid in enumerate(ref["mode_ids"]):
        b = mem(r0 + i * size, size)
        if b is None:
            continue
        emu = bytes.fromhex(ref["emulated_stock_records"][mid])
        diff = [o for o in range(size) if b[o] != emu[o]]
        recs[mid] = {"index": i, "all_zero": not any(b), "bytes_differing_from_emulation": len(diff), "offsets": [hex(o) for o in diff[:48]], "record": b.hex()}
    out["stored_records"] = recs
    t = mem(int(ref["size_table_address"], 16), 128)
    if t is not None:
        out["size_table"] = [list(struct.unpack_from("<HHI", t, 8 * k)) for k in range(16)]
    # the second scaler's state, at the FX3 dump's addresses ported to the FX6 (build/port_addr.py fx3_702 fx6_602); the block and input words
    # are the FX3's "predicted" ones, moved with the division block: NOT confirmed
    a = {k: int(v, 16) for k, v in ref["dump_addresses"].items()}
    st = {}
    blk = mem(a["second_scaler_block"], 0x20)
    if blk is not None:
        w = struct.unpack_from("<10H", blk)
        st["second_scaler_block"] = {"address": hex(a["second_scaler_block"]), "words": list(w), "start": [round(w[2] + w[6] / 4096, 3), round(w[3] + w[7] / 4096, 3)],
                                     "size": [round(w[4] + w[8] / 4096, 3), round(w[5] + w[9] / 4096, 3)]}
    inp = mem(a["second_scaler_input"], 8)
    if inp is not None:
        st["second_scaler_input"] = list(struct.unpack_from("<4H", inp))
    ws = mem(a["resize_work"], 0xDC)
    if ws is not None:
        st["resize_work"] = {"pixel_aspect_q12": struct.unpack_from("<i", ws, 0x48)[0], "scale_h_q12": struct.unpack_from("<i", ws, 0x4C)[0],
                             "scale_v_q12": struct.unpack_from("<i", ws, 0x50)[0], "zoom_q16": struct.unpack_from("<i", ws, 0x24)[0], "head": ws[:0x60].hex()}
    se = mem(a["resize_settings"], 0x20)
    if se is not None:
        st["resize_settings"] = se.hex()
    dv = mem(a["division_block"], 0x5A0)
    if dv is not None:
        st["division_units"] = [{"in_start": struct.unpack_from("<I", dv, k * 0x150 + 0xC)[0], "in_width": struct.unpack_from("<I", dv, k * 0x150 + 0x10)[0],
                                 "out_width": struct.unpack_from("<I", dv, k * 0x150 + 0x20)[0]} for k in range(4)]
    seen = {}
    pairs = {(4240, 2832), (4240, 2392), (4240, 2385), (4240, 2848), (4240, 2408), (3840, 2560), (3840, 2160), (1920, 1080), (2144, 2392), (2096, 2392), (2176, 2408)}
    for addr, (name, blob) in sorted(pages.items()):
        if name not in ("context", "resizework", "resizestate"):
            continue
        for o in range(0, 4096 - 3, 2):
            p = struct.unpack_from("<HH", blob, o)
            if p in pairs:
                seen.setdefault("%dx%d" % p, []).append(hex(addr + o))
    st["where_sizes_occur"] = {k: v[:40] for k, v in sorted(seen.items())}
    if any(n in ("context", "resizework", "resizestate") for n, _ in pages.values()):
        out["scaler_state"] = st
    # the display: the screen design's words as the camera holds them, and the panel facts the screen fork named (fx6_reference.json "display")
    disp = {}
    dref = ref.get("display", {})
    for name, addr in dref.get("bytes", {}).items():
        v = mem(int(addr, 16), 1)
        if v is not None:
            disp[name] = v[0]
    for name, (addr, n) in dref.get("words", {}).items():
        v = mem(int(addr, 16), n)
        if v is not None:
            disp[name] = v.hex()
    sw = ref.get("screen_words", [])
    if sw and all(mem(int(w["address"], 16), 4) is not None for w in sw):
        got = [mem(int(w["address"], 16), 4).hex() for w in sw]
        disp["screen_words"] = {"stock": sum(g == w["stock"] for g, w in zip(got, sw)), "new": sum(g == w["new"] for g, w in zip(got, sw)),
                                "other": sum(g not in (w["stock"], w["new"]) for g, w in zip(got, sw))}
    if disp:
        out["display"] = disp
    # the output-plane memory table (the run-time copy of DmmCfg.bin's unit records): the step's words, and the two layouts that offer the planes
    dm = ref.get("dmm") or {}
    if dm and mem(int(dm["unit_records"], 16), 20) is not None:
        words = [(w, mem(int(w["address"], 16), 4)) for w in dm["words"]]
        state = {w["address"]: ("stock" if g.hex() == w["stock"] else "new" if g.hex() == w["new"] else "other " + g.hex()) for w, g in words}
        held = {name: sum(state[a] == "new" for a in addrs) == len(addrs) and all(state[a] == "stock" for a in state if a not in addrs) for name, addrs in dm["variants"].items()}
        lay = {}
        for gid, g in dm["layouts"].items():
            raw = mem(int(g["first_record"], 16), 20 * g["records"])
            recs = [struct.unpack_from("<5I", raw, 20 * k) for k in range(g["records"])]
            total = sum(r[3] for r in recs)
            lay[gid] = {"units": [[hex(r[2]), r[3]] for r in recs], "total": total, "parent": dm["parent_size"], "spare": dm["parent_size"] - total,
                        "planes": sum(1 for r in recs if hex(r[2]) == dm["plane_key"]),
                        "planes_big_enough": sum(1 for r in recs if hex(r[2]) == dm["plane_key"] and r[3] >= dm["plane_bytes_needed"]),
                        "as_in_the_file": [[hex(r[2]), r[3]] for r in recs] == [list(u) for u in g["stock"]]}
        out["output_planes"] = {"words": state, "stock": sum(v == "stock" for v in state.values()), "new": sum(v == "new" for v in state.values()),
                                "other": sum(v.startswith("other") for v in state.values()), "design_held": [n for n, h in held.items() if h], "layouts": lay}
    # The camera core's periodic log record (FX3 0x13d7f48; FX6 0x163bac0, ported). It is the one place a dump shows state from BEFORE the USB
    # session: at dump time the sensor sleeps (drive mode 1) and the live state is the session's. +4 a time count, +8 the drive mode id,
    # +0xb [context+0x364], +0xc [context+0x368], +0xd a core state number, +0xe [context+0x2a4]. On the A7S III state 7 was standby, 9 recording.
    rec = mem(a["core_log_record"], 0x10)
    if rec is not None:
        out["core_log_record"] = {"time": struct.unpack_from("<I", rec, 4)[0], "drive_mode": hex(struct.unpack_from("<H", rec, 8)[0]), "context_0x364": rec[0xB],
                                  "context_0x368": rec[0xC], "state": rec[0xD], "context_0x2a4": rec[0xE]}
    return out


# ------------------------------------------------------------ the A7 IV runner, pointed at this camera

def known_answer(session, camera):
    want = (S3 / "DeviceInfo.xml").read_bytes()
    there, data = R.read(camera, R.KNOWN_PATH)
    if not there or data != want:
        raise c.StopTest("DeviceInfo.xml is not the file of the 6.02 update (%s); nothing else is sent"
                         % ("the camera returned no file" if not there else "%d bytes, SHA-256 %s" % (len(data), c.sha256(data)[:16])))
    session.say("Known-answer read: DeviceInfo.xml equals the 6.02 file (the A7 IV, A7S III, FX3 and FX6 have the same file: the helper itself checks which camera this is)")


def run_helper(data):
    """What loading the uploaded bytes gives on a model FX6: the real AArch64 code in Unicorn if it is installed, else a canned text."""
    if WHICH in WRITE_STEPS:                        # the write libraries are emulated by helper_fx6/emu_fx6_write.py; here only the session flow is simulated
        text = "readcheck 1 level %s\neuid 0\n== level %s\nDONE: every site holds the target bytes (canned)\n== done, bytes written before this line: 0\n" % (WHICH[1:], WHICH[1:])
        return text.encode(), "canned"
    try:
        import emu_fx6
    except Exception:
        text = "fx6read %s %s for ILME-FX6 6.02; read-only\n== file /proc/version\nLinux (simulated)\n\n== end 18 bytes\n== summary\nVERDICT READY (canned)\n== done\n" % (LABELS[-1], WHICH)
        return text.encode(), "canned"
    r, text = emu_fx6.run(bytes(data))
    if r.bad:
        raise AssertionError("the emulated helper stopped: %s" % r.bad)
    return text.encode(), "emulated"


def make_sim(lib, files=None, fault=None):
    sim = _make_sim(lib, files, fault)
    if "/usr/share/pmbp/DeviceInfo.xml" not in (files or {}):
        sim.fs["/usr/share/pmbp/DeviceInfo.xml"] = (S3 / "DeviceInfo.xml").read_bytes()
    return sim


def use(which):
    """Point the runner's module state at one of this camera's libraries."""
    global WHICH
    WHICH = which
    name, sha = PINS[which]
    if not (S3 / name).is_file():
        raise SystemExit("%s is not in this kit%s. Nothing was sent." % (name, " (the write steps are not published yet)" if which in WRITE_STEPS else ""))
    R.LEVEL, R.DESIGN, R.LIB, R.LIB_SHA256 = LEVELS[which], "og4k_data_v1", S3 / name, sha
    R.check_result, R.known_answer, R.run_helper, R.make_sim = check_result, known_answer, run_helper, make_sim
    R.KNOWN_LIBS = known_libs()
    c.EXPECTED_FIRMWARE = FIRMWARE
    return R.library()


_make_sim = R.make_sim


def selftest(lib):
    done = []

    def check(cond, what):
        if not cond:
            raise AssertionError("self-test failed: " + what)
        done.append(what)

    W, D = "SET_FILE2", "FILE_DELETE2"
    s, sim, stopped = R.simulate(lib, R.body_run)
    r = s.results.get("ct6", {})
    check(not stopped and not sim.unexpected and R.sent(s).count(W) == 1 and R.sent(s).count(D) == 1, "normal run: one write, one delete, nothing off the list")
    check(R.sent(s).index(D) < len(R.sent(s)) - 2 and R.sent(s)[-1] == "GET_FILE2", "normal run: the delete comes before the result is read")
    check(R.LIB_PATH.decode() not in sim.fs and sim.loads == 1, "normal run: the library was loaded once and is gone afterwards")
    f = r.get("result", {}).get("s3", {})
    if WHICH in WRITE_STEPS:
        check(f.get("ok") and r["result"]["header_ok"], "normal run: the step's result is read as DONE")
    else:
        check(f.get("ready") and not f.get("identity_differs"), "normal run: the %s helper reports a stock 6.02 camera as READY" % sim.how)
    if sim.how == "emulated":
        e = expected()
        check(len(f["coprocessor_sites"]) == len(e["cp_sites"]) and f["avcam_stock"] == e["av_sites"] and len(f["libmpr_sites"]) == e["lm_sites"],
              "normal run: every coprocessor site, %d libmpr and %d av-cam sites are reported" % (e["lm_sites"], e["av_sites"]))
        if WHICH == "dump":
            d = f.get("decoded", {})
            check(d.get("matrix_equals_file") and len(d.get("stored_records", {})) == 40 and d.get("size_table"), "dump: the pages decode (matrix, 40 records, size table)")
            dp = d.get("display", {})
            n_sw = len(reference().get("screen_words", []))
            check(not n_sw or dp.get("screen_words") == {"stock": n_sw, "new": 0, "other": 0}, "dump: the display pages decode (the %d screen words read stock)" % n_sw)
            n_dm = len((reference().get("dmm") or {}).get("words", []))
            op = d.get("output_planes", {})
            check(not n_dm or (op.get("stock") == n_dm and not op.get("design_held") and all(v["as_in_the_file"] and v["spare"] == 786432 for v in op["layouts"].values())),
                  "dump: the output-plane table decodes (the %d memory words read stock, both layouts as in the file)" % n_dm)
    s, sim, stopped = R.simulate(lib, R.body_run, files={R.LIB_PATH.decode(): b"someone else's"})
    check(stopped and W not in R.sent(s) and D not in R.sent(s), "a foreign libJit.so on the camera: stops, nothing written, nothing deleted")
    s, sim, stopped = R.simulate(lib, R.body_run, files={"/tmp_wbshd/readcheck_result.txt": b"old"})
    check(stopped and W not in R.sent(s), "a result already on the RAM disk: stops, nothing written")
    s, sim, stopped = R.simulate(lib, R.body_run, files={"/tmp/jbusy": b""})
    check(stopped and W not in R.sent(s), "/tmp/jbusy present: stops, nothing written")
    s, sim, stopped = R.simulate(lib, R.body_run, files={"/usr/share/pmbp/DeviceInfo.xml": b"<other camera/>"})
    check(stopped and len(R.sent(s)) == 2, "another DeviceInfo.xml: stops after the known-answer read")
    s, sim, stopped = R.simulate(lib, R.body_run, fault="load")
    check(stopped and R.sent(s).count(D) == 1 and R.LIB_PATH.decode() not in sim.fs, "a camera that cannot load the library: it is still deleted")
    # a library an earlier session left on the service partition (it survives a cold boot): one of this kit's is deleted and the run goes on
    lp = R.LIB_PATH.decode()
    other = next((S3 / n).read_bytes() for k, (n, sha) in sorted(PINS.items()) if k != WHICH and (S3 / n).is_file())
    for left, what in ((other, "another step's library"), (lib, "this step's own library")):
        s, sim, stopped = R.simulate(lib, R.body_run, files={lp: left})
        names, lr = R.sent(s), s.results["ct6"].get("leftover_removed") or {}
        check(not stopped and not sim.unexpected and names.count(D) == 2 and names.count(W) == 1 and names.index(D) < names.index(W) and lp not in sim.fs
              and sim.loads == 1 and lr.get("gone") and lr.get("sha256") == c.sha256(left) and s.results["ct6"]["library_on_camera_after"] is False,
              "%s left on the camera: deleted first, then the normal run (one write, loaded once, gone afterwards)" % what)
    named = b"a file named with --remove-library"
    saved = dict(R.KNOWN_LIBS)
    try:
        R.KNOWN_LIBS[c.sha256(named)] = "the file named with --remove-library"
        s, sim, stopped = R.simulate(lib, R.body_run, files={lp: named})
        check(not stopped and R.sent(s).count(D) == 2 and R.sent(s).count(W) == 1 and lp not in sim.fs, "--remove-library with the file's SHA-256: deleted, then the normal run")
        s, sim, stopped = R.simulate(lib, R.body_run, files={lp: named + b"!"})
        check(stopped and W not in R.sent(s) and D not in R.sent(s) and c.sha256(named + b"!") in stopped, "--remove-library with another SHA-256: stops, nothing deleted, the file's SHA-256 is shown")
    finally:
        R.KNOWN_LIBS.clear()
        R.KNOWN_LIBS.update(saved)
    s, sim, stopped = R.simulate(lib, R.body_remove_only, files={lp: other})
    check(not stopped and R.sent(s).count(D) == 1 and W not in R.sent(s) and lp not in sim.fs and s.results["ct6"]["library_on_camera_after"] is False,
          "--remove-only: deletes another step's library of this kit too, writes nothing")
    s, sim, stopped = R.simulate(lib, R.body_remove_only, files={lp: b"someone else's"})
    check(stopped and D not in R.sent(s) and lp in sim.fs, "--remove-only: leaves a file that is none of this kit's")
    check(set(EARLIER_LIBS) <= set(R.KNOWN_LIBS) and all(sha in R.KNOWN_LIBS for _, sha in PINS.values()) and not set(EARLIER_LIBS) & {sha for _, sha in PINS.values()},
          "every library of this kit, current (%d) and earlier (%d), is one a run may delete" % (len(PINS), len(EARLIER_LIBS)))
    check(len(R.refusals(lib)) == 15, "the guard refuses the 15 listed packets (changed library, other paths, backup, flash and debug writes ...)")
    return done


def report(session, facts, which):
    f = facts["s3"]
    if which in WRITE_STEPS:
        lines = ["FX6 6.02 step %s: %s" % (which, f["what"]), "OUTCOME: %s" % f["outcome"], str(f["outcome_line"])] + ["  " + ln for ln in f["problem_lines"]]
        session.save_bytes("fx6_report.txt", ("\n".join(lines) + "\n").encode())
        for ln in lines:
            session.say(ln)
        return
    lines = ["FX6 6.02 %s, %s" % (which, time.strftime("%Y-%m-%d %H:%M:%S")), f["header"], f["verdict"],
             "identity: %d same, %d differ" % (f["identity_same"], f["identity_differs"]),
             "kernel: %s" % f["kernel_version"], "command line: %s" % f["kernel_command_line"]]
    for s in f["coprocessor_sites"]:
        lines.append("  coprocessor %-16s %s len %-4d %s%s" % (s["name"], s["address"], s["length"], s["state"], "" if s["shown"] is None else "  (" + s["shown"] + ")"))
    lines += ["  " + ln for ln in f["libmpr_sites"]] + ["  " + ln for ln in f["avcam_guards"]]
    lines.append("  av-cam.bin sites: %d stock, %d target, %d other" % (f["avcam_stock"], f["avcam_target"], f["avcam_other"]))
    lines += ["problem lines:"] + ["  " + ln for ln in f["problem_lines"]] if f["problem_lines"] else ["no problem lines"]
    if f.get("expected_lines"):
        lines.append("(%d expected lines left out: folders in the helper's file list, and log files longer than the copy's limit)" % f["expected_lines"])
    d = f.get("decoded")
    if d:
        sr = d.get("sensor_registers")
        if sr:
            lines.append("sensor register shadow: closest matrix column %d (%d of %d rows equal; modes %s); window rows hold %s"
                         % (sr["closest_column"], sr["rows_equal_per_column"][sr["closest_column"]], sr["rows"], ", ".join(sr["modes_using_it"]), sr["window_rows"]))
        lines.append("register matrix equals the file: %s" % d.get("matrix_equals_file"))
        zero = [m for m, v in d.get("stored_records", {}).items() if v["all_zero"]]
        same = [m for m, v in d.get("stored_records", {}).items() if not v["bytes_differing_from_emulation"]]
        lines.append("stored drive-parameter records: %d read, %d equal to the emulated ones, %d all zero" % (len(d.get("stored_records", {})), len(same), len(zero)))
        v = d.get("stored_records", {}).get("0x8c0")
        if v:
            lines.append("  mode 0x8c0: %d bytes differ from the emulation at %s" % (v["bytes_differing_from_emulation"], ", ".join(v["offsets"])))
        if d.get("size_table"):
            lines.append("movie size table: " + "; ".join("%dx%d id %#x" % tuple(r) for r in d["size_table"]))
        ss = d.get("scaler_state")
        if ss:
            lines.append("second scaler state (addresses ported from the FX3's; the block and input words are not confirmed):")
            bl = ss.get("second_scaler_block")
            if bl:
                lines.append("  block %s: words %s -> takes %s x %s from %s" % (bl["address"], bl["words"], bl["size"][0], bl["size"][1], bl["start"]))
            if "second_scaler_input" in ss:
                lines.append("  input words: %s" % ss["second_scaler_input"])
            rw = ss.get("resize_work")
            if rw:
                lines.append("  resize work: pixel aspect %d/4096, scales %d and %d /4096, zoom %d/65536" % (rw["pixel_aspect_q12"], rw["scale_h_q12"], rw["scale_v_q12"], rw["zoom_q16"]))
            if "division_units" in ss:
                lines.append("  division units: %s" % ss["division_units"])
            for k, v in ss.get("where_sizes_occur", {}).items():
                lines.append("  %s at %s%s" % (k, ", ".join(v[:10]), " ..." if len(v) > 10 else ""))
        cl = d.get("core_log_record")
        if cl:
            lines.append("camera core's last log record before this session: time %d, drive mode %s, values %d / %d / %d (on the A7S III state 7 = standby, 9 = recording)"
                         % (cl["time"], cl["drive_mode"], cl["context_0x364"], cl["state"], cl["context_0x2a4"]))
            if cl["drive_mode"] not in ("0x8c0", "0x1"):
                lines.append("  NOTE: the open-gate design changes drive mode 0x8c0 (QFHD 23.98p, full frame). The camera ran %s: report the Imager Scan Mode, "
                             "Rec Format and frame rate that were set." % cl["drive_mode"])
        op = d.get("output_planes")
        if op:
            lines.append("output-plane memory (the step D16 / R16; a 3840 x 2560 picture needs planes of 14,745,600 bytes):")
            lines.append("  memory words: %d stock, %d applied, %d other%s" % (op["stock"], op["new"], op["other"],
                                                                                 "; holds " + " and ".join(op["design_held"]) if op["design_held"] else ""))
            for gid, v in op["layouts"].items():
                lines.append("  layout %s: %d output plane(s), %d big enough; total %s of %s bytes (%s)%s"
                             % (gid, v["planes"], v["planes_big_enough"], format(v["total"], ","), format(v["parent"], ","),
                                "%s spare" % format(v["spare"], ",") if v["spare"] >= 0 else "%s over its block: this layout now refuses a request, which dmm7slot_fx6_v1 intends" % format(-v["spare"], ","),
                                "" if not v["as_in_the_file"] else ", as in the firmware's file"))
            for a, v in op["words"].items():
                if v.startswith("other"):
                    lines.append("  !! word %s holds neither the stock nor the new value: %s" % (a, v))
        dp = d.get("display")
        if dp:
            lines.append("display (what the screen step reads and changes):")
            for k, v in dp.items():
                if k == "screen_words":
                    lines.append("  screen step words: %(stock)d stock, %(new)d applied, %(other)d other" % v)
                else:
                    lines.append("  %s: %s" % (k, v))
    session.save_bytes("fx6_report.txt", ("\n".join(lines) + "\n").encode())
    for ln in lines[:8] + [x for x in lines[8:-6] if x.startswith(("output-plane", "  memory words", "  layout"))] + lines[-6:]:
        session.say(ln)


def last_saved_sha():
    """The SHA-256 of the result the newest saved session of this kit fetched, or None."""
    root = c.PRIVATE_ROOT
    if not root.is_dir():
        return None
    for folder in sorted((p for p in root.iterdir() if p.is_dir() and p.name.startswith("CT6_")), reverse=True):
        try:
            return json.loads((folder / "manifest.json").read_text(encoding="utf8"))["results"]["ct6"]["result"]["sha256"]
        except (OSError, KeyError, TypeError, ValueError):
            continue
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("which", choices=sorted(PINS))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--remove-only", action="store_true")
    ap.add_argument("--clear-result", metavar="SHA256", help="first delete the result file of an earlier run from the RAM disk, only if its SHA-256 is this")
    ap.add_argument("--remove-library", metavar="SHA256", help="a libJit.so left on the camera's service partition that is none of this kit's: delete it first, "
                                                               "only if its SHA-256 is this (a library of this kit is deleted without being named)")
    ap.add_argument("--firmware-shown")
    ap.add_argument("--writes-memory", action="store_true", help="needed for a write step (%s): it changes the running camera's memory" % ", ".join(WRITE_STEPS))
    a = ap.parse_args()
    if a.remove_library:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", a.remove_library):
            raise SystemExit("--remove-library takes the 64 hexadecimal digits of the file's SHA-256 (the stopped run prints them). Nothing was sent.")
        EXTRA_LIBS[a.remove_library.lower()] = "the file named with --remove-library"
    if a.which in WRITE_STEPS and a.go and not (a.dry_run or a.selftest) and not a.writes_memory:
        raise SystemExit("%s is a write step: %s. It needs --writes-memory as well. Use fx6_apply.py. Nothing was sent." % (a.which, WRITE_STEPS[a.which][2]))
    lib = use(a.which)
    if a.dry_run or a.selftest:
        if a.selftest:                              # --dry-run and --selftest win over --go (the launchers always pass --go): nothing is sent
            for line in selftest(lib):
                print("PASS  " + line)
            print("all checks passed; nothing was sent to any device")
        else:
            print("\n".join(R.dry_run_lines(lib)))
        return
    if not a.go or a.firmware_shown != FIRMWARE:
        raise SystemExit("A live run needs --go and --firmware-shown %s (the version the camera's menu shows). Nothing was sent." % FIRMWARE)
    R.refusals(lib)
    selftest(lib)                                   # the flow must pass on the simulated camera on the day, before the real one
    import ct1_stage2_service as service
    # A result left on the RAM disk by the run before stops a new run. Without --clear-result the newest result saved on this PC is named: the
    # runner deletes the camera's file only if its SHA-256 is that one, i.e. only a result already here.
    R.CLEAR_SHA = a.clear_result or last_saved_sha()
    body = R.body_remove_only if a.remove_only else R.body_run
    with c.Session("remove_only" if a.remove_only else "fx6_%s" % a.which, test="CT6") as session:
        session.results.update(firmware_shown_on_camera=a.firmware_shown, model=MODEL, which=a.which, library_sha256=PINS[a.which][1],
                               pc={"platform": platform.platform(), "python": sys.version.split()[0]})
        inner = service.connect(session)
        try:
            R.service_session(session, inner, lambda cam: body(session, cam, lib), lib)
            facts = session.results.get("ct6", {}).get("result")
            if facts and not a.remove_only:
                pages = facts.pop("_pages", {})
                for addr, (name, blob) in sorted(pages.items()):
                    session.save_bytes("cp_%s_%08x.bin" % (name, addr), blob)
                report(session, facts, a.which)
        finally:
            time.sleep(3)
            c.print_pnp(session, "after the stop request")
            out = session.results.get("ct6", {})
            print("Library sent: %s. On the camera now: %s." % (
                "yes" if out.get("library_sent") else "no",
                {False: "no (confirmed)", True: "YES", None: "not sent" if not out.get("library_sent") and not a.remove_only else "UNKNOWN"}[out.get("library_on_camera_after")]))
            if a.which in WRITE_STEPS:
                print("This was a WRITE step. A cold boot (battery out for 10 seconds) undoes everything written. On the A7S III, whose coprocessor software the FX6 shares, "
                      "the power switch did too: keep the camera on between steps.")
            else:
                print("Nothing on the camera was changed. Unplug and replug the USB cable before another run; a cold boot (battery out) clears the result file.")


if __name__ == "__main__":
    main()
