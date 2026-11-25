"""Build the FX6 6.02 coprocessor design `ogsq_fx6_v1`: the FX3's working `ogsq_fx3_v1` (= the A7S III's `ogsq_s3_v5`) on the FX6's tables.

  C:/Python313/python.exe -B build/build_og_fx6.py

Why this is a port and not a new design (modding/FX6_PORT.md): the FX6 6.02 coprocessor app carries the FX3 7.02's imager code and
tables once more. The same 40 drive modes in the same order (0x8c0 = index 12, 0xe011 = index 37), every sensor table byte-identical
to the FX3's (13 tables, all 40 rows) at other addresses, and the same calculator, record selector, size-table set-up and scaler
packers (match_thumb fx3_702 -> fx6_602: one exact masked hit each). `ogsq_fx3_v1` ran on two FX3s (2026-11-24): open gate, the
whole sensor area, right colours. It is the reference; nothing new is invented here.

Checks (each must pass or nothing is written):
  identity   the FX6 image's sha256; each table the design touches is byte-identical to the FX3's (whole table, 40 rows), and the
             class table
  S cells    build/build_og_s3_v3.py's `cells()` run on the FX6 image with the FX6 table addresses (read from the FX6's table map,
             the constructor caller 0x85d36c) and v4's timing rows; the result must be ogsq_fx3_v1's 19 cells at the matching FX6
             addresses with the same old and new bytes
  records    the FX6 selector 0x261d10 (build/emu_record_selector.py) must give every mode the FX3's record moved by +0x1ac3c8 and
             0x8c0 / 0x820 the pair 0xd5f5a0 / 0xd60158. The FX6's stock pair may differ from the FX3's only in relocated pointers
             (FX3 value + 0x1ac3c8), none inside the design's changed bytes. New record = FX6 stock record with the design's changed
             bytes. Cross-check: build/build_og_s3.py's record model run on the FX6 image with the FX6's own packers gives the same two
             records byte for byte
  link rule  the 12-bit link-format rule (build/s3_linkfmt_words.py) on all FX6 stock records; both new records pass the 12-bit rule
  stored     build/emu_drvparam.py fx6_602: the 40 stock records equal the FX3's; with the cells applied, index 12 plus the 16/19 ratio
             and the run-time bytes left alone equals ogsq_fx3_v1's stored record exactly
Design only: nothing is written to a firmware file, nothing is sent to a camera. Never run on an FX6.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import build_og_fx3 as FX3  # noqa: E402
import build_og_s3 as V2  # noqa: E402
import build_og_s3_v3 as V3  # noqa: E402
import emu_drvparam  # noqa: E402
import emu_record_selector  # noqa: E402
import s3_linkfmt_words as LF  # noqa: E402

NAME, BUILD, REF = "ogsq_fx6_v1", "fx6_602", "fx3_702"
REF_DESIGN = "ogsq_fx3_v1"
BASE, SIZE = 0x108000, 0xBB8
SHA = "b432af7212a4"                                   # prefix; the full hash is checked against the extracted file and written out
# FX6 table addresses: the table map 0x85d36c (arguments of the constructor 0x85e742); colmap and geometry found by content (FX3 tables)
T_FX6 = {"ids": 0xE009FC, "colmap": 0xE007A0, "rx": 0xE0121C, "rx2": 0xE01B7C, "d": 0xE01DFC, "tim": 0xE013FC, "tim_b": 0xE013FC + 0x3C0,
         "win": 0xE9B202, "st1": 0xE9B7F2, "lc": 0xE9BDE2, "crop": 0xE00A9C, "rl": 0xE9C012, "geo": 0xDA6568}
CLASS = {REF: 0xC53B50, BUILD: 0xE00DBC}
RECORD_SHIFT = 0x1AC3C8                                # FX3 record -> FX6 record, every mode (emu_record_selector)
PAIR = {"L": 0xD5F5A0, "R": 0xD60158}
STILL = {"L": 0xD70328, "R": 0xD70EE0}                # 0xa000's full-height still pair (FX3 0xbc3f60 / 0xbc4b18)
# The one value word in which FX6 picture records differ from the FX3's: +0x460 is 0x3ffe in all 46 FX6 records (the FX3 has a value per
# mode, 0x0..0x20b). Not one of the design's changed bytes; the port keeps the FX6's value. Its meaning is not known.
FX6_WORD, FX6_WORD_VALUE = 0x460, 0x3FFE
PACKER = {"CamArc": 0x25DEF0, "CamNrs": 0x6D0A74, "CamSig": 0x6D6D9A, "CamLrc": 0x6D0A30, "Dev (first packer)": 0x6CFFA8,
          "Dev (second packer)": 0x6CFE4A, V2.G.BEYOND: 0x6CFFA8}
LOG, FIT = 0x9E8768, 0x6D69F8
STORED = 0x2196504 + 12 * 0x15C                       # index 12's stored record (records base from the table map)
SENSOR_OBJECT, PPTR = 0x14A5AEC, 0x664                 # getter 0x85b640 (FX3 0x85617e: 0x127ab68); constructor block 0x85d536 str r0, [r4, #0x664]


def fx6_cells(fx):
    """build_og_s3_v3.cells() with the FX6 tables and v4's timing rows (the rows ogsq_fx3_v1 carries)"""
    saved = V3.T, V3.TIMING
    try:
        V3.TIMING = FX3.TIMING
        V3.T = dict(T_FX6)
        cs = V3.cells(fx)
    finally:
        V3.T, V3.TIMING = saved
    return cs


def to_fx3(a):
    k = min((k for k in T_FX6 if T_FX6[k] <= a), key=lambda k: a - T_FX6[k])
    return FX3.T_FX3[k] + (a - T_FX6[k])


def link_rule(fx, sel):
    ids = struct.unpack_from("<40I", fx, T_FX6["ids"] - BASE)
    cl = {}
    for i, m in enumerate(ids):
        b = struct.unpack_from("<I", fx, T_FX6["rx"] - BASE + 12 * i + 4)[0]
        assert b in (1, 2, 3)
        for r in sel[m]:
            assert cl.setdefault(r, b == 3) == (b == 3), f"record {r:#x} serves both link classes"
    for r, ten in cl.items():
        w = lambda off: struct.unpack_from("<I", fx, r + off - BASE)[0]
        for off, (v10, v12) in LF.LINK_WORDS.items():
            assert w(off) == (v10 if ten else v12), f"FX6 record {r:#x} +{off:#x}"
        assert w(0x274) - (w(0x278) & 0xFFFF) == LF.WIDTH_EXTRA[ten]
    return cl


def main():
    des = ROOT / "modding" / "designs"
    ref = json.loads((des / f"{REF_DESIGN}.json").read_text(encoding="utf8"))
    fx, f3 = emu_drvparam.image(BUILD), emu_drvparam.image(REF)
    sha = hashlib.sha256(fx).hexdigest()
    assert sha.startswith(SHA) and ref["artifact_sha256"] == hashlib.sha256(f3).hexdigest()
    ev = {"design": NAME, "build": BUILD, "reference": f"{REF_DESIGN} ({REF}; ran on two FX3s 2026-11-24)"}

    # ---- tables
    lens = FX3.table_lengths()
    rows = []
    for k, a in T_FX6.items():
        b = FX3.T_FX3[k]
        same = fx[a - BASE:a - BASE + lens[k]] == f3[b - BASE:b - BASE + lens[k]]
        rows.append({"table": k, "fx3_702": hex(b), "fx6_602": hex(a), "bytes": lens[k], "identical": same})
        assert same, f"table {k} differs: {a:#x} against {b:#x}"
    a, b = CLASS[BUILD], CLASS[REF]
    assert fx[a - BASE:a - BASE + 40 * 8] == f3[b - BASE:b - BASE + 40 * 8], "class table differs"
    ev["tables"] = rows

    # ---- sensor cells, rebuilt on the FX6 image and compared with the FX3 design's
    cs = fx6_cells(fx)
    ref_s = {int(p["addr"], 16): p for p in ref["patches"] if p["kind"] == "S"}
    assert len(cs) == len(ref_s) == 19
    for lab, a, o, n, note in cs:
        p = ref_s[to_fx3(a)]
        assert (o.hex(), n.hex()) == (p["old"], p["new"]), (lab, hex(a))
    ev["cells"] = [{"label": lab, "fx6_602": hex(a), "fx3_702": hex(to_fx3(a)), "old": o.hex(), "new": n.hex()} for lab, a, o, n, note in cs]

    # ---- the record pair
    sel_fx, _ = emu_record_selector.records(BUILD)
    sel_f3, _ = emu_record_selector.records(REF)
    assert all([r + RECORD_SHIFT for r in sel_f3[m]] == sel_fx[m] for m in sel_f3), "the selector map is not the FX3's moved"
    assert sel_fx[0x8C0] == sel_fx[0x820] == sorted(PAIR.values())
    assert [r + RECORD_SHIFT for r in sel_f3[0xA000]][:2] == sorted(STILL.values())
    ref_r = {int(p["addr"], 16): p for p in ref["patches"] if p["kind"] == "R"}
    recs, reloc = {}, {}
    for h in "LR":
        a = PAIR[h]
        p = ref_r[a - RECORD_SHIFT]
        s_old, s_new = bytes.fromhex(p["old"]), bytes.fromhex(p["new"])
        f_old = fx[a - BASE:a - BASE + SIZE]
        assert s_old == f3[a - RECORD_SHIFT - BASE:a - RECORD_SHIFT - BASE + SIZE]
        changed = [o for o in range(SIZE) if s_old[o] != s_new[o]]
        words = sorted({o & ~3 for o in range(SIZE) if s_old[o] != f_old[o]})
        for o in words:                                  # every stock difference is a relocated pointer, or the FX6's own +0x460 word
            x, y = struct.unpack_from("<I", s_old, o)[0], struct.unpack_from("<I", f_old, o)[0]
            assert (0xB00000 < x < 0xD00000 and y == x + RECORD_SHIFT) or (o == FX6_WORD and y == FX6_WORD_VALUE), (h, hex(o), hex(x), hex(y))
        assert not set(changed) & {o + k for o in words for k in range(4)}, "an FX6-specific word inside the design's changed bytes"
        new = bytearray(f_old)
        for o in changed:
            new[o] = s_new[o]
        recs[h] = bytes(new)
        reloc[h] = [{"offset": hex(o), "fx3": hex(struct.unpack_from("<I", s_old, o)[0]), "fx6": hex(struct.unpack_from("<I", f_old, o)[0]),
                     "kind": "FX6 value (0x3ffe in every FX6 record)" if o == FX6_WORD else "relocated pointer"} for o in words]
    ev["records"] = {"selector_map": "every mode's records = the FX3's + 0x1ac3c8 (build/emu_record_selector.py)",
                     "pair": {h: hex(a) for h, a in PAIR.items()}, "relocated_pointer_words": reloc}

    # ---- cross-check: the record model on the FX6's own packers, and the same on the FX3
    rep_fx, mod_fx = FX3.model_records(fx, PAIR, STILL, PACKER, LOG, FIT)
    rep_f3, mod_f3 = FX3.model_records(f3, FX3.PAIR, FX3.STILL, FX3.PACKER, FX3.LOG, FX3.FIT)
    for rep in (rep_fx, rep_f3):
        assert all(not rep[h]["off_rule"] and not any(rep[h]["packer_words_not_reproduced_on_stock"].values()) for h in "LR"), rep
    for h in "LR":
        assert mod_f3[h] == bytes.fromhex(ref_r[FX3.PAIR[h]]["new"]), f"the model does not reproduce ogsq_fx3_v1's {h} record on the FX3"
        assert mod_fx[h] == recs[h], f"the FX6 packers' {h} record differs from the ported one"
    g = lambda h, o: struct.unpack_from("<H", recs[h], o)[0]
    lrc = {h: {"input": [g(h, 0x160), g(h, 0xE)], "output": [g(h, 0x178), g(h, 0x17A)], "crop_rows": [g(h, 0x13A), g(h, 0x13E)], "final": [g(h, 0x194), g(h, 0x196)]}
           for h in "LR"}
    assert lrc == ref["lrc"], lrc
    ev["model_check"] = {"fx6_packers_reproduce_stock_words": True, "fx6_model_records_equal_port": True, "fx3_model_reproduces_reference": True, "lrc": lrc}

    # ---- link-format rule
    cl = link_rule(fx, sel_fx)
    assert cl[PAIR["L"]] and cl[PAIR["R"]]
    for h in "LR":
        w = lambda off: struct.unpack_from("<I", recs[h], off)[0]
        assert all(w(o) == v12 for o, (_, v12) in LF.LINK_WORDS.items()) and w(0x274) - (w(0x278) & 0xFFFF) == LF.WIDTH_EXTRA[False]
    ev["link_rule"] = {"records_10_bit": sum(cl.values()), "records_12_14_bit": len(cl) - sum(cl.values())}

    # ---- stored record
    st_fx, l0 = emu_drvparam.records(BUILD)
    st_f3, l1 = emu_drvparam.records(REF)
    assert not l0 and not l1 and all(st_fx[m][1] == st_f3[m][1] for m in st_f3), "stock stored records differ from the FX3's"
    new_fx, l2 = emu_drvparam.records(BUILD, [(a, n) for _, a, _, n, _ in cs])
    assert not l2
    others = [hex(m) for m in st_fx if m != 0x8C0 and st_fx[m][1] != new_fx[m][1]]
    assert not others, others
    (i0, s_rec, e0), (i1, n_rec, e1) = st_fx[0x8C0], new_fx[0x8C0]
    assert i0 == i1 == 12 and not e0 and not e1
    d_rec = bytearray(n_rec)
    d_rec[6], d_rec[7] = 16, 19
    for o in V3.RUNTIME:
        d_rec[o] = s_rec[o]
    sr = ref["stored_record"]
    assert s_rec.hex() == sr["stock"] and bytes(d_rec).hex() == sr["design"], "the FX6 stored record differs from ogsq_fx3_v1's"
    diff = [o for o in range(emu_drvparam.REC) if s_rec[o] != d_rec[o]]
    ev["stored_record"] = {"stock_40_records_equal_fx3": True, "design_equals_reference": True, "bytes": len(diff), "address": hex(STORED)}

    # ---- the design file
    patches = []
    for lab, a, o, n, note in cs:
        p = ref_s[to_fx3(a)]
        patches.append({"kind": "S", "addr": hex(a), "old": o.hex(), "new": n.hex(), "where": "file",
                        "note": p["note"].split(" | FX3:")[0] + f" | FX6: FX3 {to_fx3(a):#x}"})
    for h, nm in (("L", "left"), ("R", "right")):
        a = PAIR[h]
        patches.append({"kind": "R", "addr": hex(a), "old": fx[a - BASE:a - BASE + SIZE].hex(), "new": recs[h].hex(), "where": "file",
                        "note": f"0x8c0/0x820 {nm} record: the FX3 design's changed bytes on the FX6's stock record (FX3 {a - RECORD_SHIFT:#x}; relocated pointers kept)"})
    out = {"design": NAME, "build": BUILD, "camera": "ILME-FX6 (FX6), firmware 6.02",
           "title": "ogsq_fx3_v1 (the FX3's working open-gate sensor state, itself the A7S III's ogsq_s3_v5) on the FX6's tables: drive mode 0x8c0 on the "
                    "full-height sensor mode of 0xe011, 12-bit link, 2848-row first stage squeezed by Lrc into the stock picture; vertical sampling ratio 16/19",
           "status": "built from the firmware files and emulated (FX6 calculator, selector, packers); never run on an FX6. The same design works on two FX3s",
           "artifact": "cpapp-b.bin", "artifact_sha256": sha, "generated_by": "build/build_og_fx6.py",
           "ported_from": f"{REF_DESIGN} ({REF})", "mode_id": "0x8c0", "mode_index": 12, "sensor_mode_taken_from": "0xe011 (index 37)",
           "sensor_object": hex(SENSOR_OBJECT), "drive_parameter_pointer_offset": hex(PPTR),
           "timing": ref["timing"], "summary": {"sites": len(patches), "bytes": sum(len(p["new"]) // 2 for p in patches), "sensor_cells": len(cs), "records": 2},
           "lrc": lrc, "patches": patches,
           "stored_record": {"address": hex(STORED), "stock": s_rec.hex(), "design": bytes(d_rec).hex(), "offsets_that_differ": [hex(o) for o in diff],
                             "run_time_offsets_left_alone": sr["run_time_offsets_left_alone"]},
           "guesses": ref["guesses"],
           "not_shown": ["anything on an FX6",
                         "which drive mode the FX6 runs for QFHD 23.98p: its 24p chooser (0x40e518, the FX3's 0x407b2c byte for byte) gives 0x8c0 for "
                         "the QFHD class unless [settings+0x6a8] == 2 (then 0x28c0) or a Super 35 flag [settings+0x66c] is 1 / 2 (0x8c4 / 0xbc5 -> 0xbc4); "
                         "appFw (the FX6's own) fills those fields. The read-only check reports the drive mode the camera runs"] + ref["not_shown"][1:]}
    (des / f"{NAME}.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf8", newline="\n")
    evd = ROOT / "evidence" / "fx6"
    evd.mkdir(parents=True, exist_ok=True)
    (evd / f"{NAME}_checks.json").write_text(json.dumps(ev, indent=1) + "\n", encoding="utf8", newline="\n")
    print(f"{NAME}: {len(cs)} sensor cells + 2 records = {len(patches)} sites, {out['summary']['bytes']} bytes; stored record {len(diff)} bytes at {STORED:#x}")
    print(f"  tables identical to the FX3's: {len(ev['tables'])}; cells = ogsq_fx3_v1's at the FX6 addresses; relocated pointer words "
          f"{ {h: len(v) for h, v in reloc.items()} }")
    print(f"  FX6 packers rebuild both records byte for byte; link rule on {len(cl)} FX6 records; stored record = the FX3 design's; lrc {json.dumps(lrc)}")
    print("wrote", des / f"{NAME}.json", "and", evd / f"{NAME}_checks.json")


if __name__ == "__main__":
    main()
