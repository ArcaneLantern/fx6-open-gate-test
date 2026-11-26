"""Write fx6_expected.h for fx6read.c from the FX6 6.02 files and the port designs.

  work/venv/Scripts/python.exe -I -B gen_fx6.py

The FX6 6.02 counterpart of helper_fx3/gen_fx3.py (the FX3 helper, which ran on two FX3s). Everything the helper compares against is
taken here from the extracted 6.02 update and from modding/designs/{ogsq_fx6_v1, outsz2560_fx6_v1, <encoder design>, <screen design>}.json;
the helper holds no other constant about the camera except the addresses listed at the top of this file. Differences from the FX3
helper: the FX6's addresses (modding/FX6_PORT.md: tables found by content and through the table map, RAM pages ported by code reference
with build/port_addr.py fx3_702 fx6_602), its own register matrix (the FX3's 489 rows in order plus 7 all-zero rows after row 59), the
av-cam guards named by the encoder design, and the display words named by the screen design. Read-only on the inputs.
"""
import hashlib
import json
import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EX = ROOT / "work/extracted/fx6_602/0700_part_image/dev"
OTHER = {b: ROOT / "work/extracted" / b / "0700_part_image/dev/nflasha8/cpapp-b.bin" for b in ("fx3_702", "a7s3_501", "zve1_202", "a7c2_201", "fx2_101", "fx30_601")}
DES = ROOT / "modding/designs"
BASE = 0x108000
LABEL = "fx6read_v2"                                  # v2 (2026-11-26, after the testers' first runs): the output-plane memory words and their table pages
CP_LO, CP_HI = 0xC0000, 0x2200000                     # coprocessor addresses a read may have: its logs (tomco.txt: same as the FX3's), image and RAM tables
AVCAM_PHYS, AVCAM_RESERVE = 0x401000000, "@0x401000000"   # kemco.txt (6.02, appli): memrsv=0x01000000@0x401000000:ex, as on the FX3; checked on the camera before any read
ID_FILES = {"/libmpr.so": "nflasha15/lib/libmpr.so", "/libsencore.so": "nflasha15/lib/libsencore.so", "/libJiritsu.so": "nflasha15/lib/libJiritsu.so"}
# code pages (0x85d000 holds the drive-parameter table map, the FX3's 0x857000) and a constant-data page (the FX6's constant data starts near
# 0xae5f30, where the FX3's 0xaea720 is); none holds a design site, and each differs from the page at the same address in every other kit's body
ID_PAGES = (0x128000, 0x4A8000, 0x85D000, 0xAE7000)
# RAM pages of the dump (FX3 kit's dump at the FX6's addresses):
#   shadow     the sensor register shadow 0x11d68b4.. (the matrix rows' addresses; FX3 0xff4bf0)
#   matrix     the register matrix 0x10ea3a8, 496 rows (FX3 0xf09f84, 489 rows)
#   sizetable  the movie size table 0x1626b7c (build/emu_size_table.py fx6_602)
#   records    the stored drive-parameter records 0x2196504, 40 x 0x15c (the table map's field 0x10)
#   kprint / bootlog   the coprocessor's logs (tomco.txt 6.02: klog 0xe0000, boottime 0xc0000, as the FX3)
#   context / resizework / resizestate / wbuf   the second scaler's state (build/port_addr.py fx3_702 fx6_602: saved records 0x13af9d0 / 0x13afa08
#              (3 / 2 votes), resize work 0x13c2868 (3), division block 0x163b2e4 (2), core log record 0x163bac0 (1), settings 0x163cbcc (1),
#              write-buffer ring 0x13a6a48 (6))
DUMP_RANGES = [("shadow", 0x11D6000, 2), ("matrix", 0x10EA000, 3), ("sizetable", 0x1626000, 1), ("records", 0x2196000, 4),
               ("kprint", 0xE0000, 32), ("bootlog", 0xC0000, 8),
               ("context", 0x13AF000, 5), ("resizework", 0x13C2000, 1), ("resizestate", 0x1639000, 5), ("wbuf", 0x13A6000, 3)]
DUMP_ADDRESSES = {"second_scaler_block": 0x163B2E4 - 0x44C, "second_scaler_input": 0x163B2E4 - 0x44C + 0x3C, "resize_work": 0x13C2868,
                  "resize_settings": 0x163CBCC, "division_block": 0x163B2E4, "core_log_record": 0x163BAC0}
MATRIX, COLMAP, IDS, RECS, REC = 0x10EA3A8, 0xE007A0, 0xE009FC, 0x2196504, 0x15C
SIZE_TABLE = 0x1626B7C
DESIGNS = {"sensor": "ogsq_fx6_v1", "size": "outsz2560_fx6_v1"}         # the encoder, screen and memory designs are named in kit.json


def c_bytes(b):
    return "{" + ",".join(str(x) for x in b) + "}"


def kit_designs():
    """The encoder and screen design names this kit carries (kit.json beside this file, written when the designs are chosen)."""
    k = json.loads((HERE / "kit.json").read_text(encoding="utf8"))
    return k


def dmm_reference(kit, dm, cfgbin):
    """What the PC needs to read the output-plane part of a dump: the words of each variant, and the two layouts' records."""
    import sys
    sys.path.insert(0, str(ROOT / "build"))
    import parse_dmmcfg as P
    cfg = P.Config(P.find_file("fx6_602"), "fx6_602")
    base = P.RAM["fx6_602"]["unit_records"]
    assert base == int(kit["dmm_regions"][0][0], 16)
    lay = {}
    for gid in (0x26, 0x28):
        g = next(g for g in cfg.groups if g["gid"] == gid)
        lay[hex(gid)] = {"first_record": hex(base + g["units"][0]["seq"] * 0x14), "records": len(g["units"]),
                         "stock": [[hex(u["key"]), u["size"]] for u in g["units"]]}
    variant = {d["design"]: [s["ram_address"] for s in d["sites"]] for d in dm[:-1]}
    return {"unit_records": hex(base), "end": kit["dmm_regions"][0][1], "parent_size": 106954752, "plane_key": "0x3f1", "plane_bytes_needed": 14745600,
            "layouts": lay, "variants": variant,
            "words": [{"address": s["ram_address"], "stock": s["old"], "new": s["new"], "note": s["note"]} for s in dm[-1]["sites"]]}


def main():
    kit = kit_designs()
    cp = (EX / "nflasha8/cpapp-b.bin").read_bytes()
    av = (EX / "nflasha3/av-cam.bin").read_bytes()
    lm = (EX / "nflasha15/lib/libmpr.so").read_bytes()
    og, oz = (json.loads((DES / f"{n}.json").read_text(encoding="utf8")) for n in (DESIGNS["sensor"], DESIGNS["size"]))
    fl = json.loads((DES / f"{kit['encoder']}.json").read_text(encoding="utf8"))
    sc = json.loads((DES / f"{kit['screen']}.json").read_text(encoding="utf8")) if kit.get("screen") else None
    assert og["artifact_sha256"] == oz["emulated_image_sha256"] == hashlib.sha256(cp).hexdigest()
    assert sc is None or sc["artifact_sha256"] == hashlib.sha256(cp).hexdigest()
    shas = {"libmpr.so": hashlib.sha256(lm).hexdigest(), "av-cam.bin": hashlib.sha256(av).hexdigest()}
    assert all(fl["artifact_sha256"][k] == shas[k] for k in fl["artifact_sha256"]) and set(fl["artifact_sha256"]) <= set(shas), \
        "the encoder design names a file the helper does not read"
    out, blobs = [], []

    def blob(b):
        blobs.append(f"static const unsigned char B{len(blobs)}[] = {c_bytes(b)};")
        return f"B{len(blobs) - 1}"

    out.append(f'#define FX6_LABEL "{LABEL}"\n#define CP_LO {CP_LO:#x}U\n#define CP_HI {CP_HI:#x}U\n#define AVCAM_PHYS {AVCAM_PHYS:#x}UL\n'
               f'#define AVCAM_RESERVE "{AVCAM_RESERVE}"')
    out.append("struct id_file { const char *name; unsigned char sha256[32]; };\nstruct id_page { unsigned int address; unsigned char sha256[32]; };\n"
               "struct cp_site { const char *name; unsigned int address, length; const unsigned char *stock, *target; int soft; };\n"
               "struct mp_site { unsigned long offset; unsigned int length; const unsigned char *stock, *target; };\n"
               "struct av_guard { const char *name; unsigned long offset; unsigned int length; unsigned char sha256[32]; };\n"
               "struct dump_range { const char *name; unsigned int address, pages; };")
    rows = [f'    {{"{n}", {c_bytes(hashlib.sha256((EX / p).read_bytes()).digest())}}},' for n, p in ID_FILES.items()]
    out.append("static const struct id_file id_files[] = {\n" + "\n".join(rows) + "\n};")
    # identity pages: constant (code or constant data), no site in them, and different from the same address in every other body's image
    others = {b: p.read_bytes() for b, p in OTHER.items() if p.is_file()}
    for a in ID_PAGES:
        page = cp[a - BASE:a - BASE + 4096]
        for b, img in others.items():
            assert img[a - BASE:a - BASE + 4096] != page, f"identity page {a:#x} equals {b}'s"
    rows = [f"    {{{a:#x}, {c_bytes(hashlib.sha256(cp[a - BASE:a - BASE + 4096]).digest())}}}," for a in ID_PAGES]
    out.append("static const struct id_page id_pages[] = {\n" + "\n".join(rows) + "\n};")
    # ---- coprocessor sites
    sites = []
    for p in og["patches"]:
        a, old, new = int(p["addr"], 16), bytes.fromhex(p["old"]), bytes.fromhex(p["new"])
        assert cp[a - BASE:a - BASE + len(old)] == old and len(old) == len(new)
        name = p["note"].split(" ")[0] if p["kind"] == "S" else ("record_left" if "left" in p["note"] else "record_right")
        sites.append((name, a, old, new, 0))
    sr = og["stored_record"]
    # soft: the camera fills parts of this record at run time, so it need not equal the emulated one; reported, not counted
    sites.append(("stored_record", int(sr["address"], 16), bytes.fromhex(sr["stock"]), bytes.fromhex(sr["design"]), 1))
    for s in oz["sites"]:                                 # soft: the size table is zero until a movie mode has run
        sites.append(("outsize", int(s["ram_address"], 16), bytes.fromhex(s["old"]), bytes.fromhex(s["new"]), 1))
    for k, g in enumerate(oz["guards"]):
        sites.append((f"outsize_guard{k}", int(g["ram_address"], 16), bytes.fromhex(g["bytes"]), None, 1))
    dm = [json.loads((DES / (kit[k] + ".json")).read_text(encoding="utf8")) for k in ("dmm", "dmm_alt", "dmm_back") if kit.get(k)]
    cfgbin = (EX / "nflasha8/DmmCfg.bin").read_bytes()
    for k, s in enumerate(dm[-1]["sites"] if dm else ()):   # the output-plane words (the put-back design lists every word of both variants)
        f = int(s["file_offset"], 16)
        assert dm[-1]["dmmcfg_sha256"] == hashlib.sha256(cfgbin).hexdigest() and cfgbin[f:f + 4] == bytes.fromhex(s["old"])
        sites.append((f"dmm{k}", int(s["ram_address"], 16), bytes.fromhex(s["old"]), bytes.fromhex(s["new"]), 0))
    for k, s in enumerate(sc["sites"] if sc else ()):     # soft: the screen step is optional (apply --screen); reported, not counted
        a = int(s["ram_address"], 16)
        assert cp[a - BASE:a - BASE + 4] == bytes.fromhex(s["old"])
        sites.append((f"screen{k}", a, bytes.fromhex(s["old"]), bytes.fromhex(s["new"]), 1))
    rows = []
    for name, a, old, new, soft in sites:
        assert CP_LO <= a and a + len(old) <= CP_HI and len(old) <= 3072
        assert not any(p <= a < p + 4096 or p <= a + len(old) - 1 < p + 4096 for p in ID_PAGES), f"site {name} lies in an identity page"
        rows.append(f'    {{"{name}", {a:#x}, {len(old)}, {blob(old)}, {blob(new) if new is not None else "0"}, {soft}}},')
    out.append("static const struct cp_site cp_sites[] = {\n" + "\n".join(rows) + "\n};")
    # ---- main-processor sites
    lmr, avr, av_hi = [], [], 0
    for p in fl["patches"]:
        o, old, new = int(p["file_off"], 16), bytes.fromhex(p["old"]), bytes.fromhex(p["new"])
        assert p["binary"] in ("libmpr.so", "av-cam.bin"), p["binary"]
        src = lm if p["binary"] == "libmpr.so" else av
        assert src[o:o + len(old)] == old
        (lmr if p["binary"] == "libmpr.so" else avr).append(f"    {{{o:#x}UL, {len(old)}, {blob(old)}, {blob(new)}}},")
        if p["binary"] == "av-cam.bin":
            av_hi = max(av_hi, o + len(old))
    out.append("static const struct mp_site lm_sites[] = {\n" + "\n".join(lmr) + "\n};")
    out.append("static const struct mp_site av_sites[] = {\n" + ("\n".join(avr) if avr else "    {0, 0, 0, 0}") + "\n};")
    # av-cam.bin guards: pieces of its tables that no site touches, named by the encoder design (fork's build_ogfile_fx6.py)
    guards = [(g["name"], int(g["file_off"], 16), int(g["length"])) for g in kit["avcam_guards"]]
    spans = [(int(p["file_off"], 16), len(p["old"]) // 2) for p in fl["patches"] if p["binary"] == "av-cam.bin"]
    rows = []
    for name, o, n in guards:
        assert all(o + n <= so or so + sn <= o for so, sn in spans), name
        rows.append(f'    {{"{name}", {o:#x}UL, {n}, {c_bytes(hashlib.sha256(av[o:o + n]).digest())}}},')
        av_hi = max(av_hi, o + n)
    out.append("static const struct av_guard av_guards[] = {\n" + "\n".join(rows) + "\n};")
    av_lo = min([so for so, _ in spans] + [o for _, o, _ in guards]) & ~0xFFF
    out.append(f"#define AV_LO {av_lo:#x}UL\n#define AV_HI {av_hi:#x}UL")
    dump = DUMP_RANGES + [(n, int(a, 16), k) for n, a, k in kit.get("display_pages", []) + kit.get("dmm_pages", [])]
    rows = [f'    {{"{n}", {a:#x}, {k}}},' for n, a, k in dump]
    assert all(CP_LO <= a and a + 4096 * k <= CP_HI for _, a, k in dump)
    out.append("#if DUMP\nstatic const struct dump_range dump_ranges[] = {\n" + "\n".join(rows) + "\n};\n#endif")
    text = ("/* Generated by gen_fx6.py from the FX6 6.02 files and the port designs. Do not edit. */\n#ifndef DUMP\n#define DUMP 0\n#endif\n"
            + "\n".join(blobs) + "\n" + "\n".join(out) + "\n")
    (HERE / "fx6_expected.h").write_text(text, encoding="utf8", newline="\n")
    used = [og, oz, fl] + ([sc] if sc else []) + dm
    facts = {"label": LABEL, "cp_lo": CP_LO, "cp_hi": CP_HI, "avcam_phys": AVCAM_PHYS, "avcam_reserve": AVCAM_RESERVE,
             "id_files": {n: hashlib.sha256((EX / p).read_bytes()).hexdigest() for n, p in ID_FILES.items()},
             "id_pages": {hex(a): hashlib.sha256(cp[a - BASE:a - BASE + 4096]).hexdigest() for a in ID_PAGES},
             "cp_sites": [{"name": n, "address": hex(a), "length": len(o), "soft": s} for n, a, o, _, s in sites],
             "lm_sites": len(lmr), "av_sites": len(avr), "av_guards": [g[0] for g in guards], "dump_ranges": [[n, hex(a), k] for n, a, k in dump],
             "designs": {d["design"]: hashlib.sha256((DES / (d["design"] + ".json")).read_bytes()).hexdigest() for d in used}}
    (HERE / "fx6_expected.json").write_text(json.dumps(facts, indent=1) + "\n", encoding="utf8", newline="\n")
    # ---- what the PC needs to read a dump without the firmware files
    matrix, k = [], 0
    while struct.unpack_from("<I", cp, MATRIX - BASE + 16 * k)[0]:
        matrix.append([struct.unpack_from("<I", cp, MATRIX - BASE + 16 * k)[0], cp[MATRIX - BASE + 16 * k + 4:MATRIX - BASE + 16 * k + 16].hex()])
        k += 1
    assert len(matrix) == 496
    assert all(DUMP_RANGES[0][1] <= a < DUMP_RANGES[0][1] + 4096 * DUMP_RANGES[0][2] for a, _ in matrix), "a shadow address outside the shadow pages"
    emu = json.loads((ROOT / "evidence/fx6/drvparam_stock_fx6_602.json").read_text(encoding="utf8"))["modes"]
    # the FX3 tools' window rows 6, 7, 24, 42 are the same rows here (they come before the 7 inserted rows; evidence/fx6/matrix_alignment.json)
    ref = {"about": "FX6 6.02 reference data for reading an fx6read dump; from cpapp-b.bin and build/emu_drvparam.py", "matrix_address": hex(MATRIX),
           "matrix": matrix, "window_rows": [6, 7, 24, 42], "column_map": [list(struct.unpack_from("<2I", cp, COLMAP - BASE + 8 * i)) for i in range(40)],
           "mode_ids": [hex(x) for x in struct.unpack_from("<40I", cp, IDS - BASE)], "records_address": hex(RECS), "record_size": REC,
           "emulated_stock_records": {m: v["record"] for m, v in emu.items()}, "size_table_address": hex(SIZE_TABLE),
           "dump_addresses": {k: hex(v) for k, v in DUMP_ADDRESSES.items()},
           "stored_record_design": {"mode": "0x8c0", "index": og["mode_index"], "stock": sr["stock"], "design": sr["design"]},
           "display": kit.get("display_reference", {}),
           "dmm": dmm_reference(kit, dm, cfgbin) if dm else {},
           "screen_words": [{"address": s["ram_address"], "stock": s["old"], "new": s["new"], "note": s["note"]} for s in (sc["sites"] if sc else ())]}
    assert len(ref["emulated_stock_records"]) == 40
    (HERE / "fx6_reference.json").write_text(json.dumps(ref) + "\n", encoding="utf8", newline="\n")
    print(f"fx6_expected.h: {len(sites)} coprocessor sites ({len(sc['sites']) if sc else 0} of the screen), {len(lmr)} libmpr sites, {len(avr)} av-cam sites, "
          f"{len(guards)} av-cam guards, {len(dump)} dump ranges, {len(text)} bytes of header")


if __name__ == "__main__":
    main()
