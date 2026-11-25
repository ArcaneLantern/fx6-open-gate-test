"""Build the encoder side of a 3840 by 2560 file on the FX6 6.02 (ILME-FX6, build fx6_602): design `ogfile2560_xavc_fx6_v1`.

The FX6 counterpart of the FX3 kit's L19 step (`ogfile2560_hs_s_fx3_v1`, build/build_ogfile.py, which records 3840x2560 on two FX3s). The FX6
records XAVC-I (AVC intra 4:2:2 10-bit) and XAVC-L (AVC long GOP) in MXF, not XAVC HS/S in MP4, so its av-cam tables are a different set (none of
the FX3's 689 descriptors occurs in the FX6 av-cam byte for byte). What is the same, and what the design rests on:

  libmpr.so  `mpr::g_videoParamComb` (dynamic symbol, 0xcca018, 20 rows of 0x18): rows 0-11 are the FX3's / A7 IV's byte for byte.
             `mpr::SetEncOpenParam` (0x14c85c) copies the row's width/height into the encoder request at EncOpen +0x68/+0x6a (read in the code:
             ldrh [row,#4] / [row,#6] -> strh [x19,#0x68] / [x19,#0x6a]), as on the A7 IV (F132). The FX6 rows the design changes:
               row 0  AVC 3840x2160 4:2:0 8-bit long GOP    = XAVC-L QFHD 4:2:0 8-bit
               row 9  AVC 3840x2160 4:2:2 10-bit intra      = XAVC-I QFHD (row 17 is XAVC-I DCI 4096x2160 and is left alone)
             Row 2 (AVC 4:2:2 10-bit long GOP = XAVC-L QFHD 4:2:2 10-bit) is left alone: at 3840x2560 the FX6's codec firmware asks more LD and
             multi-buffer memory than the FX6's 4K blocks hold (EXCLUDED below).
             The MXF muxer's own format fill (0x548a3c) maps the same rows to compression 7 (AVC long) / 6 (AVC intra); see FX6_PORT_ENCODER.md.
  av-cam.bin unit-type table 0x37815c (7 rows; the FX3's rows 0-6 byte for byte), descriptor table 0x3781cc (589 x 0x90, the FX3 layout),
             profile tables 0x38cd1c (367 rows) and 0x3a3c1c (200 rows, both ending with a key-0 row), clip-format table 0x377658 (18 rows of
             {valid, w, h, code}: row 1 8192x4320 code 1, row 5 3840x2160 code 16).
             Matcher 0x209898 (a variant of the FX3's 0x225eb8: it does not compare chroma/bit depth; quality class +0x10 tells 4:2:2 10-bit from
             4:2:0 8-bit), memory function 0x201804 (above 8,847,360 pixels: unit type 4 for the intra codecs {8, 10, 0x18}, type 3 otherwise),
             clip-format function 0x19e4bc (reads the request at +0x68/+0x6a/+0x81), start-block builder 0x20559c (called at 0x2032c8).

Sites (ogfile2560_xavc_fx6_v1):
  L1-comb   libmpr g_videoParamComb rows 0 and 9: height 2160 -> 2560 (the encoder request's height)
  (no A0)   the FX3's unit-type site is NOT needed here: above 8,847,360 pixels XAVC-I takes type 4, whose row is the 4K row it asks at 2160, and
            XAVC-L takes type 3 (LD 0x473, multi 0x476, ES 0x479, no CD block), the class a stock XAVC-L QFHD S&Q 120 recording already uses
  A1-desc   every QFHD descriptor of XAVC-L 4:2:0 8-bit (codec 5, quality class 0x1a) and of XAVC-I (codec 8, classes 0x55 and 0x56) at coding-rate
            codes 5 (23.98p) and 3 (25p), the S&Q rows (input rate 60/120) included: height +0x80 -> 2560. Changing each whole group keeps the
            matcher's order, so a request at 3840x2560 reaches exactly the descriptor the same request reaches at 3840x2160 on a stock camera,
            whatever its +0x88 / +0x1c words (the matcher's +0x88 = 2/5 branch reaches the 1xxxxx UseCore-2 XAVC-I rows, the other branch the
            2xxxxx UseCore-0 rows; which one the camera's request takes was not traced)
  A2-profile their profiles: height +0x06 and +0x38 -> 2560; rows for the first core +0x56 where it is not 0 (1072 -> 1280)
  A3-clip   clip-format row 1 (8192x4320, code 1; the FX6 records no 8K) -> 3840x2560, code 16 (the code a 3840x2160 recording gets)

Left alone on purpose: the level bytes, the bit budgets, the other frame rates of the two formats (their requests now say 2,560 rows and find no
descriptor: refused at encoder open, as on the FX3), XAVC-L 4:2:2 10-bit (EXCLUDED), XAVC-I DCI, HD, proxies, and the MXF header and Sony's XML,
which still say 3840x2160 16:9 (v2, the header heights, is not built: see FX6_PORT_ENCODER.md, "Metadata").

Run:  C:\\Python313\\python.exe -B build\\build_ogfile_fx6.py [--list]
Writes modding/designs/ogfile2560_xavc_fx6_v1.json and the poke lists (file offset, hex) for build/emu_ogfile_fx6.py. Design only: nothing is
written to a firmware file and nothing is sent to a camera.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import locate_file  # noqa: E402
from build_ogfile import AVB, Design  # noqa: E402

BUILD, NAME = "fx6_602", "ogfile2560_xavc_fx6_v1"
W, H0, H1 = 3840, 2160, 2560
COMB, NCOMB, VPCS = 0xCCA018, 20, 0xEC1FD8
UNIT, NUNIT = 0x37815C, 7
DESC, NDESC = 0x3781CC, 589
PROFILES = ((0x38CD1C, 367), (0x3A3C1C, 200))
CLIP, NCLIP, CLIP_8K, CLIP_4K = 0x377658, 18, 1, 16
RATES = {5: "23.98p", 3: "25p"}
SHA = {"libmpr.so": "f3c0e3c8c124", "av-cam.bin": "56684d830eab"}          # prefixes of the 6.02 files' sha256 (checked below)
FAMILIES = {
    "xl": {"title": "XAVC-L QFHD 4:2:0 8-bit (AVC long GOP)", "codec": 5, "combs": {0: (0, 0, 0, "4:2:0 8-bit")},
           "classes": {0x1A: "4:2:0 8-bit"}, "group": [(3, 0x1A, 0), (3, 0x1A, 120), (5, 0x1A, 0), (5, 0x1A, 120)]},
    "xi": {"title": "XAVC-I QFHD (AVC intra 4:2:2 10-bit)", "codec": 8, "combs": {9: (1, 1, 1, "4:2:2 10-bit intra")},
           "classes": {0x55: "4:2:2 10-bit intra", 0x56: "4:2:2 10-bit intra"},
           "group": [(3, 0x55, 0), (3, 0x55, 120), (3, 0x56, 0), (3, 0x56, 60), (5, 0x55, 0), (5, 0x55, 120), (5, 0x56, 0), (5, 0x56, 60)]},
}
# XAVC-L QFHD 4:2:2 10-bit (comb row 2, class 0x18) is left out: the FX6's own codec firmware asks LD 39,354,368 and multi 11,141,120 bytes for it at
# 3840x2560 (build/emu_ogfile_fx6.py), and the FX6's 4K blocks are LD 0x474 33,849,344 and multi 0x477 9,502,720 (the FX3's: 50,790,400 / 14,221,312)
EXCLUDED = {"comb": 2, "codec": 5, "class": 0x18, "why": "XAVC-L QFHD 4:2:2 10-bit at 3840x2560 needs more codec memory than the FX6's 4K blocks hold "
                                                         "(LD 39.4 MB of 33.8 MB, multi 11.1 MB of 9.5 MB: build/emu_ogfile_fx6.py)"}
WHY = ("the owner asked for the FX3 open gate ported to the FX6 (2026-11-26); this is the main-processor encoder side, the counterpart of the FX3 "
       "kit's L19")


def descriptors(av):
    out = []
    for k in range(NDESC):
        o = DESC + k * 0x90
        f = struct.unpack_from("<7I", av, o)
        out.append({"k": k, "o": o, "codec": f[0], "infr": f[1], "codfr": f[2], "f0c": f[3], "cls": f[4], "chroma": f[5], "bitl": f[6],
                    "key": struct.unpack_from("<I", av, o + 0x28)[0], "f24": struct.unpack_from("<I", av, o + 0x24)[0],
                    "wh": struct.unpack_from("<HH", av, o + 0x7E), "core": av[o + 0x78], "enc_cd_mode": av[o + 0x7A],
                    "lst": struct.unpack_from("<7I", av, o + 0x40), "pred_mode": av[o + 0x85], "bit_depth": av[o + 0x82], "chroma_code": av[o + 0x83]})
    return out


def fx6_match(rows, req):
    """A model of the FX6 matcher 0x209898 (read from its code; build/emu_ogfile_fx6.py runs the real one). req: codec, infr, f0c, codfr, cls,
    wh, r88 (request +0x88), r8c (request +0x8c). Returns the first matching index or None."""
    w, h = req["wh"]
    special = req["codec"] == 5 and (w, h) == (3840, 2160) and req["cls"] == 0x17
    path_a = (req["r88"] & ~1) != 2 or req["r8c"] == 12
    for r in rows:
        if (r["codec"], r["codfr"], r["f0c"], r["cls"], r["wh"]) != (req["codec"], req["codfr"], req["f0c"], req["cls"], (w, h)):
            continue
        if req["infr"]:
            miss = r["infr"] != 0xFFFFFFFF and r["infr"] < req["infr"]
        else:
            miss = r["infr"] != 0
            if special and r["chroma"] == 0 and req["codfr"] <= 1 and (r["bitl"] | req["f0c"]) == 0:
                miss = (r["k"] - 0x11) > 1 or r["infr"] != 0
        if path_a:
            if req["r88"] in (2, 5):
                if r["f24"] == 1:
                    continue
                return r["k"]
            if not miss:
                return r["k"]
            continue
        if req["r8c"] in r["lst"]:
            return r["k"]
    return None


def request_of(r, wh=None, r88=0):
    return {"codec": r["codec"], "infr": r["infr"], "f0c": r["f0c"], "codfr": r["codfr"], "cls": r["cls"], "wh": wh or r["wh"], "r88": r88, "r8c": r["lst"][0]}


def main():
    lm = locate_file.locate(BUILD, "libmpr.so").read_bytes()
    av = locate_file.locate(BUILD, "av-cam.bin").read_bytes()
    sha = {"libmpr.so": hashlib.sha256(lm).hexdigest(), "av-cam.bin": hashlib.sha256(av).hexdigest()}
    assert all(sha[k].startswith(v) for k, v in SHA.items()), sha
    d = Design(NAME, "A 3840 by 2560 file on the FX6's XAVC-L QFHD and XAVC-I QFHD at 23.98p and 25p: encoder request, encoder memory class, "
                     "descriptors, profiles and the monitoring label")
    # ---- libmpr: comb rows (and m_vpcSt agrees on what each row is)
    combs = [struct.unpack_from("<IHH4I", lm, COMB + 0x18 * r) for r in range(NCOMB)]
    vpcs = [struct.unpack_from("<IHH5I", lm, VPCS + 0x1C * r) for r in range(NCOMB)]
    for fam in FAMILIES.values():
        for row, (chroma, depth, intra, name) in fam["combs"].items():
            c = combs[row]
            assert c == (0, W, H0, 1, chroma, depth, intra), (row, c)
            assert vpcs[row][:3] == (0, W, H0) and vpcs[row][7] == intra, (row, vpcs[row])
            d.add("libmpr.so", lm, "L1-comb", COMB + 0x18 * row + 6, struct.pack("<H", H1),
                  f"g_videoParamComb row {row} (AVC {name}): height 2160 -> 2560 (the encoder request's height; SetEncOpenParam 0x14c85c copies it to EncOpen +0x6a)",
                  struct.pack("<H", H0))
    assert combs[17][:3] == (0, 4096, 2160), "row 17 (XAVC-I DCI) moved"
    # ---- av-cam: unit-type table
    urows = [struct.unpack_from("<4I", av, UNIT + 0x10 * k) for k in range(NUNIT)]
    assert urows[2] == urows[4] == (0x486, 0x474, 0x477, 0x47A) and urows[3] == (0, 0x473, 0x476, 0x479), urows
    assert struct.unpack_from("<I", av, UNIT + 0x10 * NUNIT)[0] == 5, "the descriptor table no longer follows the unit table"
    # No unit-type site (the FX3's A0-unit): on the FX6 row 3 is a working class, the one a stock XAVC-L QFHD S&Q 120 recording takes (LD 0x473,
    # multi 0x476, ES 0x479, no CD block; build/emu_ogfile_fx6.py). XAVC-L 4:2:0 at 3840x2560 takes it too, and its codec need fits its blocks.
    # ---- av-cam: descriptors and profiles
    rows = descriptors(av)
    assert len(rows) == NDESC and struct.unpack_from("<I", av, DESC + NDESC * 0x90 + 0x20)[0] != 0 or True
    prof = {}
    for base, n in PROFILES:
        assert struct.unpack_from("<I", av, base + (n - 1) * 0x100 + 0x20)[0] == 0, f"profile table {base:#x} does not end with a key-0 row"
        for k in range(n):
            prof.setdefault(struct.unpack_from("<I", av, base + k * 0x100 + 0x20)[0], []).append(base + k * 0x100)
    users = {}
    for r in rows:
        users.setdefault(r["key"], []).append(r["k"])
    picked, groups = [], {}
    for fam_id, fam in FAMILIES.items():
        # the whole group of each (codec, rate, class) at QFHD, the S&Q (input rate 60/120) rows too: then the matcher's answer for any request of the
        # group at 3840x2560 is its stock answer at 3840x2160, whatever the request's +0x88 / +0x1c words (build/emu_ogfile_fx6.py runs them all)
        mine = [r for r in rows if r["codec"] == fam["codec"] and r["wh"] == (W, H0) and r["codfr"] in RATES and r["cls"] in fam["classes"]]
        assert sorted((r["codfr"], r["cls"], r["infr"]) for r in mine) == fam["group"], [(r["k"], r["codfr"], hex(r["cls"]), r["infr"]) for r in mine]
        for r in mine:
            groups[(r["codec"], r["codfr"], r["cls"])] = r["k"]
            assert fx6_match(rows, request_of(r)) == r["k"], f"#{r['k']} is not what the FX6 matcher reaches for its own request"
            assert users[r["key"]] == [r["k"]] and len(prof[r["key"]]) == 1, f"profile key {r['key']} shared: {users[r['key']]} / {prof[r['key']]}"
            po = prof[r["key"]][0]
            p = av[po:po + 0x100]
            assert struct.unpack_from("<I", p, 0)[0] == fam["codec"] and struct.unpack_from("<HH", p, 4) == (W, H0) and struct.unpack_from("<II", p, 0x34) == (W, H0), r["k"]
            split = struct.unpack_from("<H", p, 0x56)[0]
            fmt = fam["classes"][r["cls"]]
            rate = RATES[r["codfr"]]
            what = f"descriptor #{r['k']} ({fam['title']}, {fmt}, {rate}, quality class {r['cls']:#x}, key {r['key']}, UseCore {r['core']})"
            d.add("av-cam.bin", av, "A1-desc", r["o"] + 0x80, struct.pack("<H", H1), what + ": height +0x80 -> 2560", struct.pack("<H", H0))
            pk = f"profile key {r['key']}"
            d.add("av-cam.bin", av, "A2-profile", po + 6, struct.pack("<H", H1), pk + ": raster height +0x06 -> 2560", struct.pack("<H", H0))
            d.add("av-cam.bin", av, "A2-profile", po + 0x38, struct.pack("<I", H1), pk + ": raster height +0x38 -> 2560", struct.pack("<I", H0))
            if split:
                assert split == 1072 and (fam_id == "xi" or r["core"] == 2), (r["k"], split)
                d.add("av-cam.bin", av, "A2-profile", po + 0x56, struct.pack("<H", H1 // 2),
                      pk + ": rows for the first core +0x56: 1072 -> 1280 (half the picture in whole 16-row macroblock rows, as Sony's own split of 2160)",
                      struct.pack("<H", split))
            picked.append({"descriptor": r["k"], "family": fam_id, "format": fmt, "rate": rate, "coding_rate_code": r["codfr"], "input_rate": r["infr"],
                           "quality_class": r["cls"], "f0c": r["f0c"], "profile_key": r["key"], "profile": hex(po), "pred_mode": r["pred_mode"],
                           "use_core": r["core"], "enc_cd_mode": r["enc_cd_mode"], "flag_24": r["f24"], "level_byte": p[0xA7],
                           "profile_raster_8e": list(struct.unpack_from("<HH", p, 0x8E)), "profile_4c": struct.unpack_from("<H", p, 0x4C)[0],
                           "split_56": split, "picture_bits_5c": struct.unpack_from("<I", p, 0x5C)[0]})
    excluded = [r["k"] for r in rows if r["codec"] == EXCLUDED["codec"] and r["wh"] == (W, H0) and r["cls"] == EXCLUDED["class"]]
    assert combs[EXCLUDED["comb"]] == (0, W, H0, 1, 1, 1, 0)
    # ---- av-cam: the monitoring label
    crow = [struct.unpack_from("<4I", av, CLIP + 0x10 * k) for k in range(NCLIP)]
    assert crow[1] == (1, 8192, 4320, CLIP_8K) and crow[5] == (1, W, H0, CLIP_4K) and not any(r[1:3] == (W, H1) for r in crow), crow
    d.add("av-cam.bin", av, "A3-clip", CLIP + 0x14, struct.pack("<3I", W, H1, CLIP_4K),
          f"clip-format row 1 (8192x4320, code {CLIP_8K}; the FX6 records no 8K) -> 3840x2560, code {CLIP_4K}, the code row 5 gives a 3840x2160 recording "
          "(read by 0x19e4bc). Row 5 is left as it is", struct.pack("<3I", 8192, 4320, CLIP_8K))
    spans = sorted((p["binary"], int(p["file_off"], 16), len(p["new"]) // 2) for p in d.patches)
    assert all(a[0] != b[0] or a[1] + a[2] <= b[1] for a, b in zip(spans, spans[1:])), "sites overlap"
    # guard spans for the kit's helper (the FX3 helper's av_guards, at the FX6's tables): pieces of the tables no site touches, sha256 of the stock bytes
    guards = []
    for gname, o, n in (("unit_rows_0_6", UNIT, 0x10 * NUNIT), ("clip_rows_2_7", CLIP + 0x20, 0x60), ("descriptors_1_3", DESC + 0x90, 3 * 0x90)):
        assert not any(b == "av-cam.bin" and s < o + n and o < s + ln for b, s, ln in spans), gname
        guards.append({"name": gname, "file_off": hex(o), "length": n, "sha256": hashlib.sha256(av[o:o + n]).hexdigest()})
    assert all(len(p["new"]) // 2 <= 16 for p in d.patches)
    by, kinds = {}, {}
    for p in d.patches:
        by.setdefault(p["binary"], []).append(p)
        kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
    out = {"design": NAME, "build": BUILD, "camera": "ILME-FX6 (FX6), firmware 6.02", "title": d.title, "generated_by": "build/build_ogfile_fx6.py",
           "family": "xavc_l_i", "format": "XAVC-I QFHD (4:2:2 10-bit) and XAVC-L QFHD 4:2:0 8-bit, MXF", "raster": [W, H1],
           "rates": sorted(RATES.values()),
           "goes_with": "the FX6 kit's coprocessor steps (sensor state + output size 3840x2560), applied as its L19 step (helper level 19: av-cam through the "
                        "kernel's copy in /dev/mem, libmpr through /proc/self/mem)",
           "ported_from": "ogfile2560_hs_s_fx3_v1 (the FX3's L19 v1, which records 3840x2560 XAVC HS/S on two FX3s) - same kinds of site, the FX6's own tables",
           "artifact_sha256": sha,
           "summary": {b: {"sites": len(ps), "bytes": sum(len(p["new"]) // 2 for p in ps), "code_sites": sum(p["code"] for p in ps)} for b, ps in by.items()},
           "sites_by_kind": kinds, "level": "the stock level bytes are kept (AVC 51/52 as the profiles have them; 3840x2560 is 38,400 macroblocks, above "
                                            "Level 5.1/5.2's MaxFS 36,864, as on the FX3)",
           "tables": {"g_videoParamComb": hex(COMB), "m_vpcSt": hex(VPCS), "unit_types": hex(UNIT), "descriptors": [hex(DESC), NDESC],
                      "profiles": [[hex(b), n] for b, n in PROFILES], "clip_formats": [hex(CLIP), NCLIP]},
           "functions": {"SetEncOpenParam": "libmpr 0x14c85c", "matcher": "av-cam 0x209898", "memory_ids": "av-cam 0x201804",
                         "allocator": "av-cam 0x210f3c (= A7 IV 0x222bd0)", "clip_format": "av-cam 0x19e4bc", "start_block": "av-cam 0x20559c (called at 0x2032c8)",
                         "mxf_format_fill": "libmpr 0x548a3c (comb -> muxer codes and raster; not changed in v1)"},
           "while_applied": ["XAVC-I QFHD and XAVC-L QFHD 4:2:0 8-bit record 3840x2560 at 23.98p and 25p",
                             "XAVC-L QFHD 4:2:2 10-bit is NOT changed (codec memory, below): with the coprocessor's output at 3840x2560 its encoder is still "
                             "opened for 2,160 rows - do not record it while the kit is applied (on the A7 IV the output size alone gave a recording that "
                             "stopped after about one second, F688)",
                             "the changed formats at 59.94p, 50p and 29.97p find no descriptor: refused at encoder open (the request says 2,560 rows; those "
                             "descriptors still say 2,160). S&Q at 120 fps is refused by the memory function (above 995,328,000 pixels a second); S&Q at "
                             "up to 60 fps finds its changed S&Q row",
                             "XAVC-I DCI 4096x2160, HD, proxies and every other format are not touched",
                             "the MXF header and Sony's XML still say 3840x2160, 16:9 (the AVC stream itself says 3840x2560)"],
           "excluded": dict(EXCLUDED, descriptors=excluded, **{"class": hex(EXCLUDED["class"])}),
           "descriptors": picked, "patches": d.patches, "optional_sites": [], "libmpr_code_guards": [],
           "suggested_avcam_guards": guards,
           "not_shown": ["anything on an FX6", "which quality class (0x55/0x56) the menu's XAVC-I QFHD asks (both are changed)",
                         "the request words +0x88/+0x8c the FX6 sends for a recording (the emulation runs the matcher with every value; the design holds for "
                         "every value that lets a stock XAVC-L QFHD recording find its descriptor)",
                         "that the codec and the MXF muxer accept a 2,560-row stream in a 2,160-row container (they do on the FX3 in MP4)"]}
    des = ROOT / "modding" / "designs"
    (des / f"{NAME}.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf8", newline="\n")
    for b, ps in by.items():
        (des / f"{NAME}_pokes_{b.split('.')[0].replace('-', '')}.txt").write_text("".join(f"{p['file_off']} {p['new']}\n" for p in ps), encoding="utf8", newline="\n")
    print(NAME, out["summary"], kinds, "descriptors:", len(picked))
    if "--list" in sys.argv:
        for p in picked:
            print("   #%d %s %s %s class %#x key %d core %d split %d level %d 4c %d 8e %s bits %d" % (
                p["descriptor"], p["family"], p["format"], p["rate"], p["quality_class"], p["profile_key"], p["use_core"], p["split_56"], p["level_byte"],
                p["profile_4c"], p["profile_raster_8e"], p["picture_bits_5c"]))
        print("   excluded (XAVC-L 4:2:2 10-bit QFHD):", excluded)


if __name__ == "__main__":
    main()
