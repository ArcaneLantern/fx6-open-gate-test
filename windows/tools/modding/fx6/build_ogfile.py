"""Build the encoder and container side of a 3840 by 2560 file that rides on a stock 4K recording format (A7 IV 6.02):
designs `ogfile2560_hs_v1` (XAVC HS 4K, HEVC) and `ogfile2560_s_v1` (XAVC S 4K, AVC). Design only: nothing is written
to a firmware file and nothing is sent to a camera.

It goes with the baseline (dmmwb4688_v1 + ogsq_v3) and the output size (outsz2560_v1) in the coprocessor. The stock
format stays selected in the menus; the camera is told nothing new. What changes is what the two programs on the main
processor hold for that format at 23.98p and 25p:

  libmpr.so (in the im.elf process)
    L1  g_videoParamComb rows of the format: height 2160 -> 2560. SetEncOpenParam copies it into the encoder request
        (EncOpen +0x68/+0x6a), so av-cam is asked for 3840 by 2560. Data in a read-only page.
  av-cam.bin (in the kernel, under liro.ko), all data
    A0  unit-type table row 3 := row 2. A request above 8,847,360 pixels takes the 8K class's memory ids
        (0xffffffc0012136c4), which this camera does not have; row 3 is given the 4K class's ids
    A1  the format's 3840x2160 descriptors at coding-rate codes 5 (23.98p) and 3 (25p), normal speed: height -> 2560. The matcher
        compares the raster exactly, and ImolaCreateCh takes its Hsize/Vsize from the matched descriptor
    A2  their profiles: +0x06 and +0x38 height, +0x8c height where the row holds a raster there, +0x56 split height
        (half the picture for each of the two cores) where it is not 0
    A3  clip-format row 1 (8192x4320, code 1; no format of this camera uses it) -> 3840x2560, code 16: the label the
        monitoring outputs get for a 3840x2160 recording

Left alone on purpose: the container's own height (MP4 track 0x222b90 / 0x222bdc and the NRT metadata 0x118210 are
code immediates, and libmpr's codec-name and profile-compatibility lookups know only the stock sizes). The file is
then a 3840 by 2560 stream in a container that says 3840 by 2160. The MP4 immediate is listed under `optional_sites`.

Run:  work\\venv\\Scripts\\python.exe -I -B build\\build_ogfile.py [--level6] [--list] [--register [--only <design>]]
It also writes `ogfile2560_hs_s_v1`, the union of the two, for a camera that is to record 3840 by 2560 in either format.
Writes modding/designs/ogfile2560_<family>_v1.json and poke lists (file offset, hex) for the emulators.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

import capstone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import locate_file  # noqa: E402

W, H0, H1 = 3840, 2160, 2560
AVB = 0xFFFFFFC001000000
COMB = 0x2D32B8
DESC, NDESC = 0xFFFFFFC00138393C - AVB, 689
PROFILE_TABLES = ((0xFFFFFFC00139BCCC - AVB, 373), (0xFFFFFFC0013B32CC - AVB, 316))
UNIT_TABLE = 0xFFFFFFC00138389C - AVB
CLIP = 0xFFFFFFC001381AF0 - AVB
RATES = {5: "23.98p", 3: "25p"}
# --rate30 (2026-11-26, the FX3 kit: open gate at 29.97p as well, owner's request): rate code 2 (29.97p) joins the design. On the FX3 one encoder
# core serves every stock 4K long-GOP rate up to 59.94p (all its 3840x2160 descriptors at codes 0-5 have UseCore 0), so 3840x2560 at 29.97p
# (295 million pixels a second) keeps one core as 23.98p and 25p do. Only with --meta; the union design is then written as _v3.
RATE30 = "--rate30" in sys.argv
if RATE30:
    RATES[2] = "29.97p"


def rate_text():
    v = list(RATES.values())
    return " and ".join(v) if len(v) < 3 else ", ".join(v[:-1]) + " and " + v[-1]
BUILD, SUFFIX = "a7iv_602", ""
CLIP_8K, CLIP_4K = 1, 16                 # clip-format codes of rows 1 (8192x4320) and 5 (3840x2160)
MP4_IMM = {"hs": 0x222BDC, "s": 0x222B90}
# Other builds: the same tables, moved. The shifts and codes come from build/port_sites.py and a direct read of the
# tables (evidence/a7s3/port_ogfile2560_hs_s_v1.json); every assert below is then run against that build's own files.
OTHER_BUILDS = {
    "a7s3_501": {"suffix": "_s3", "comb": 0x2D32B8 + 0x1150, "av_shift": 0xA02C, "clip": 0x38BBDC, "clip_8k": 3, "clip_4k": 23,
                 "mp4_imm": {"hs": 0x223D10, "s": 0x223CC4}},
    # A7C II 2.01 (2026-11-24): port_sites.py gives libmpr -0x57B0 (4/4), av-cam +0xDF50 (100/101; the miss is the clip row);
    # clip table read directly at 0x38F710 (row 1 8192x4320 code 3, row 5 3840x2160 code 23); MP4 immediates in libmpr by context (-0x390C).
    "a7c2_201": {"suffix": "_c2", "comb": 0x2D32B8 - 0x57B0, "av_shift": 0xDF50, "clip": 0x38F710, "clip_8k": 3, "clip_4k": 23,
                 "mp4_imm": {"hs": 0x21F2D0, "s": 0x21F284}},
    # FX3 7.02 (2026-11-24, modding/FX3_PORT.md): the A7S III's tables moved as one. av-cam +0x77A0 against the A7S III (unit types 0x395068,
    # descriptors 0x395108 689 x 0x90, profile tables 0x3ad498 / 0x3c4a98, all byte-identical to the A7S III's); clip table read at 0x39335c
    # (A7S III + 0x7780; codes 3 / 23); libmpr g_videoParamComb 0x2cb108 (A7S III - 0x9300, found by content: 4/4 sites); MP4 immediates by
    # disassembly (both `mov w6, #0x870`; the HS block now branches back to the shared tail).
    "fx3_702": {"suffix": "_fx3", "comb": 0x2D32B8 + 0x1150 - 0x9300, "av_shift": 0xA02C + 0x77A0, "clip": 0x39335C, "clip_8k": 3, "clip_4k": 23,
                "mp4_imm": {"hs": 0x220074, "s": 0x21FF3C}},
    # ZV-E1 2.02 (2026-11-24, modding/ZVE1_PORT_PART_A.md): libmpr comb -0x205C0 (port_sites 4/4); MP4 immediates by context (-0x1AE04).
    # av-cam's descriptor table CHANGED SHAPE: 647 descriptors of 0x88 bytes (8 zero bytes at +0x54 removed, so every field from +0x5c on
    # sits 8 lower), straight after the unit-type table 0x38f848 (the unit-type rows are the A7 IV's); profile records keep the 0x100
    # layout, tables 0x3a50a0 (350 rows) and 0x3baea0 (299 rows), each ending with a key-0 row as on the A7 IV. Clip table read at 0x38d7ec
    # (row 1 8192x4320 code 3, row 5 3840x2160 code 23, as the A7S III and A7C II).
    "zve1_202": {"suffix": "_zv", "comb": 0x2D32B8 - 0x205C0, "unit": 0x38F848, "desc": 0x38F8E8, "ndesc": 647, "dsize": 0x88, "dtail": 8,
                 "profiles": ((0x3A50A0, 350), (0x3BAEA0, 299)), "clip": 0x38D7EC, "clip_8k": 3, "clip_4k": 23,
                 "mp4_imm": {"hs": 0x207DD8, "s": 0x207D8C}},
    # FX2 1.01 (2026-11-25, modding/FX2_PORT_ENCODER.md): libmpr g_videoParamComb 0x2cdc58 (A7 IV - 0x5660, found by content: the A7 IV's first
    # 768 bytes of the table, once). av-cam: the unit-type table 0x3acf90 is the A7 IV's byte for byte (10 rows); the descriptors follow it as on
    # the A7 IV (0x3ad030, 691 rows of 0x90 bytes, the A7 IV's layout; two more than the A7 IV's 689, other order), then the two profile tables
    # 0x3c54e0 (376 rows) and 0x3dcde0 (315 rows), each ending with a key-0 row (codec 0x1c here, 0x19 on the A7 IV); every descriptor key has
    # its profile. Clip table read at 0x3aaeb4 (row 1 8192x4320 code 3, row 5 3840x2160 code 23, as the A7S III / A7C II / ZV-E1). MP4
    # immediates in the writer's track config 0x21f364 (= A7 IV 0x222b18 - 0x37b4, 155 of 160 instructions the same, the 5 others its
    # jump-table page offsets): `mov w6, #0x870` at 0x21f428 (HEVC) and 0x21f3dc (AVC).
    "fx2_101": {"suffix": "_fx2", "comb": 0x2D32B8 - 0x5660, "unit": 0x3ACF90, "desc": 0x3AD030, "ndesc": 691, "dsize": 0x90, "dtail": 0,
                "profiles": ((0x3C54E0, 376), (0x3DCDE0, 315)), "clip": 0x3AAEB4, "clip_8k": 3, "clip_4k": 23,
                "mp4_imm": {"hs": 0x21F428, "s": 0x21F3DC}},
    # FX30 6.01 (2026-11-26, modding/FX30_PORT_ENCODER.md): av-cam's unit-type table, descriptors (689 x 0x90) and both profile tables are the
    # FX3's byte for byte, 0x29b0 lower (unit 0x3926b8, descriptors 0x392758, profiles 0x3aaae8 / 0x3c20e8; A7 IV + 0xee1c); the clip table is the
    # FX3's too, at 0x39061c (FX3 - 0x2d40; codes 3 / 23), read by the clip function 0x1956c0. Matcher 0x224490, memory function 0x21c40c are the
    # A7 IV's whole bodies and read these addresses. libmpr g_videoParamComb 0x2cb138 (the FX3's 768 bytes, FX3 + 0x30); the MP4 writer is the FX3's
    # 0x2c higher (track config 0x21fef0): `mov w6, #0x870` at 0x2200a0 (HEVC) and 0x21ff68 (AVC).
    "fx30_601": {"suffix": "_fx30", "comb": 0x2CB138, "av_shift": 0xEE1C, "clip": 0x39061C, "clip_8k": 3, "clip_4k": 23,
                 "mp4_imm": {"hs": 0x2200A0, "s": 0x21FF68}},
    # A1 II 4.00 (2026-11-26, modding/A1M2_PORT_ENCODER.md): av-cam's unit-type table 0x3ab234 is the A7 IV's byte for byte (10 rows); 686
    # descriptors of 0x90 bytes follow it (0x3ab2d4; the A7 IV's 689 less three, the same 4K set); profile tables 0x3c34b4 (371 rows) and 0x3da8b4
    # (315), each ending with a key-0 row; clip table 0x3a9158 (codes 3 / 23). Row 3's ids have memory on the A1 II (it records 8K), but its CD id
    # is 0 (skipped by the A1 II's memory function 0x22c9e8) and its ES id 0x479 is the alternative of the 4K CD 0x486 in the same 304.7 MB block:
    # a 3840x2560 long-GOP channel still needs row 3 := row 2. libmpr g_videoParamComb 0x2d2ca8 (the A7 IV's 768 bytes, -0x610); the MP4 writer is
    # the A7 IV's moved by +0x15c4 (track config 0x2240dc): `mov w6, #0x870` at 0x2241a0 (HEVC) and 0x224154 (AVC).
    "a1m2_400": {"suffix": "_a1m2", "comb": 0x2D2CA8, "unit": 0x3AB234, "desc": 0x3AB2D4, "ndesc": 686, "dsize": 0x90, "dtail": 0,
                 "profiles": ((0x3C34B4, 371), (0x3DA8B4, 315)), "clip": 0x3A9158, "clip_8k": 3, "clip_4k": 23,
                 "mp4_imm": {"hs": 0x2241A0, "s": 0x224154}},
    # A6700 2.00 (2026-11-26, modding/A6700_PORT_ENCODER.md): av-cam's unit-type table (0x393648), its 689 descriptors of 0x90 bytes (0x3936e8)
    # and the clip-format table (0x39156c, codes 3 / 23) are the FX30's byte for byte, 0xf90 higher (the clip table 0xf50); the profile tables
    # follow the descriptors as on the FX30 (0x3aba78, 373 rows; 0x3c3078, 316 rows; each ending with a key-0 row). libmpr.so is another
    # compile (3,180,832 bytes): g_videoParamComb 0x27e590 has 12 rows (the A7 IV's rows 0 to 11), and the MP4 writer's track config 0x1ec14c
    # keeps the height in w5 and the width in w6: `mov w5, #0x870` at 0x1ec2e8 (HEVC) and 0x1ec1b8 (AVC).
    "a6700_200": {"suffix": "_a6700", "comb": 0x27E590, "av_shift": 0xEE1C + 0xF90, "clip": 0x39156C, "clip_8k": 3, "clip_4k": 23,
                  "mp4_imm": {"hs": 0x1EC2E8, "s": 0x1EC1B8}, "mp4_reg": 5},
}
MP4_REG = 6                              # the register the track config holds the height in (A6700: w5)
DSIZE, DTAIL = 0x90, 0                   # descriptor size; how much lower the fields from +0x5c on sit (ZV-E1: 8)


def df(off):
    """Offset of a descriptor field given by its A7 IV offset."""
    return off - DTAIL if off >= 0x5C else off


def use_build(name):
    """Point the module's table addresses at another build (the A7 IV 6.02 values are the defaults above)."""
    global BUILD, SUFFIX, COMB, DESC, NDESC, PROFILE_TABLES, UNIT_TABLE, CLIP, CLIP_8K, CLIP_4K, MP4_IMM, DSIZE, DTAIL, MP4_REG
    if name == "a7iv_602":
        return
    b = OTHER_BUILDS[name]
    MP4_REG = b.get("mp4_reg", 6)
    BUILD, SUFFIX, COMB = name, b["suffix"], b["comb"]
    if "av_shift" in b:                  # the same tables, moved as one
        sh = b["av_shift"]
        DESC, UNIT_TABLE = DESC + sh, UNIT_TABLE + sh
        PROFILE_TABLES = tuple((o + sh, n) for o, n in PROFILE_TABLES)
    else:                                # tables of another shape: given one by one
        DESC, NDESC, UNIT_TABLE, PROFILE_TABLES, DSIZE, DTAIL = b["desc"], b["ndesc"], b["unit"], b["profiles"], b["dsize"], b["dtail"]
    CLIP, CLIP_8K, CLIP_4K, MP4_IMM = b["clip"], b["clip_8k"], b["clip_4k"], b["mp4_imm"]
FAMILIES = {
    "hs": {"title": "XAVC HS 4K (HEVC)", "codec": 0xE, "comb_codec": 1, "level6": 180, "level_off": 0x9E,
           "combs": {5: (1, 1, "HEVC 4:2:0 10-bit"), 7: (2, 1, "HEVC 4:2:2 10-bit")}, "groups": {(0, 1): "4:2:0 10-bit", (1, 1): "4:2:2 10-bit"}},
    "s": {"title": "XAVC S 4K (AVC)", "codec": 4, "comb_codec": 0, "level6": 60, "level_off": 0xA7,
          "combs": {0: (1, 0, "AVC 4:2:0 8-bit"), 2: (2, 1, "AVC 4:2:2 10-bit")}, "groups": {(0, 0): "4:2:0 8-bit", (1, 1): "4:2:2 10-bit"}},
}
WHY = ("the output size alone (request 26, F688) leaves the encoder opened for 2,160 rows; the owner asked for the encoder side of a 3840 by 2560 file on a "
       "stock format (2026-11-18)")


def movz_w(rd, imm):
    return struct.pack("<I", 0x52800000 | (imm << 5) | rd)


class Design:
    def __init__(self, name, title):
        self.name, self.title, self.patches, self.optional = name, title, [], []

    def add(self, binary, data, kind, off, new, note, old=None, code=False, optional=False):
        cur = data[off:off + len(new)]
        if old is not None:
            assert cur == old, f"{binary} old bytes at {off:#x}: {cur.hex()} != {old.hex()} ({note})"
        assert cur != new, f"{binary} {off:#x}: nothing to change ({note})"
        (self.optional if optional else self.patches).append(
            {"binary": binary, "kind": kind, "file_off": hex(off), "va": hex(off + AVB if binary == "av-cam.bin" else off), "old": cur.hex(), "new": new.hex(),
             "note": note, "code": code})


def build(fam, lm, av, level6):
    f = FAMILIES[fam]
    d = Design(f"ogfile2560_{fam}{SUFFIX}_v1" + ("_l6" if level6 else ""),
               f"A 3840 by 2560 file on {f['title']} at {rate_text()}: encoder request, encoder memory class, descriptors, profiles and the monitoring label")
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    # ---- libmpr
    for row, (chroma, depth, name) in f["combs"].items():
        o = COMB + 0x18 * row
        codec, w, h = struct.unpack_from("<IHH", lm, o)
        assert (codec, w, h) == (f["comb_codec"], W, H0), (row, codec, w, h)
        d.add("libmpr.so", lm, "L1-comb", o + 6, struct.pack("<H", H1), f"g_videoParamComb row {row} ({name}): height 2160 -> 2560 (the encoder request's height)",
              struct.pack("<H", H0))
    imm = MP4_IMM[fam]
    i = next(md.disasm(lm[imm:imm + 4], imm))
    assert (i.mnemonic, i.op_str) == ("mov", "w%d, #0x870" % MP4_REG), (i.mnemonic, i.op_str)
    d.add("libmpr.so", lm, "L2-mp4", imm, movz_w(MP4_REG, H1), "MP4 track height for the format's rows: 2160 -> 2560. Not part of the design: the "
          "profile-compatibility lookups behind it (0x222714) know only the stock sizes and were not followed", code=True, optional=True)
    # ---- av-cam: the memory class
    rows = [struct.unpack_from("<4I", av, UNIT_TABLE + 0x10 * k) for k in range(5)]
    assert rows[2] == (0x486, 0x474, 0x477, 0x47A) and rows[3] == (0, 0x473, 0x476, 0x479) and rows[4] == rows[2], rows
    d.add("av-cam.bin", av, "A0-unit", UNIT_TABLE + 0x30, struct.pack("<4I", *rows[2]),
          ("unit-type table row 3 (above 8,847,360 pixels; ids 0, 0x473, 0x476, 0x479, none of which has memory on this camera) := row 2 "
           "(the 4K class: frame buffer CD 0x486, LD 0x474, multi buffer 0x477, ES buffer 0x47a)") if BUILD != "a1m2_400" else
          ("unit-type table row 3 (above 8,847,360 pixels; the A1 II's 8K class: no CD (id 0, skipped by its memory function 0x22c9e8), LD 0x473, "
           "multi buffer 0x476, ES 0x479, which DO have memory on the A1 II but whose ES block is the alternative of the 4K CD 0x486 in one 304.7 MB "
           "block, so a single-core 4K channel cannot take them) := row 2 (the 4K class: frame buffer CD 0x486, LD 0x474, multi buffer 0x477, ES "
           "buffer 0x47a). While applied, XAVC HS 8K recordings get the 4K blocks too: do not record 8K"), struct.pack("<4I", *rows[3]))
    # ---- av-cam: descriptors and profiles
    prof_off = {}
    for base, n in PROFILE_TABLES:
        for k in range(n):
            prof_off.setdefault(struct.unpack_from("<I", av, base + k * 0x100 + 0x20)[0], []).append(base + k * 0x100)
    key_users = {}
    for k in range(NDESC):
        key_users.setdefault(struct.unpack_from("<I", av, DESC + k * DSIZE + 0x28)[0], []).append(k)
    picked, done = [], set()
    for k in range(NDESC):
        o = DESC + k * DSIZE
        codecid, infr, codfr, f0c, f10, chroma, bitl = struct.unpack_from("<7I", av, o)
        key = struct.unpack_from("<I", av, o + 0x28)[0]
        if struct.unpack_from("<HH", av, o + df(0x7E)) != (W, H0) or codecid != f["codec"] or (chroma, bitl) not in f["groups"] or codfr not in RATES:
            continue
        if infr:                 # input rate 120: slow and quick recording, which the baseline's sensor mode does not serve
            continue
        picked.append({"descriptor": k, "format": f["groups"][(chroma, bitl)], "rate": RATES[codfr], "coding_rate_code": codfr, "input_rate": infr,
                       "quality_class": f10, "f0c": f0c, "profile_key": key, "pred_mode": av[o + df(0x85)], "use_core": av[o + df(0x78)]})
        d.add("av-cam.bin", av, "A1-desc", o + df(0x80), struct.pack("<H", H1),
              f"descriptor #{k} ({f['groups'][(chroma, bitl)]}, {RATES[codfr]}, input rate {infr}, quality class {f10}, key {key}): height -> 2560", struct.pack("<H", H0))
        if key in done:
            continue
        done.add(key)
        assert len(prof_off[key]) == 1, (key, prof_off[key])
        others = [x for x in key_users[key] if struct.unpack_from("<HH", av, DESC + x * DSIZE + df(0x7E)) != (W, H0)
                  or struct.unpack_from("<I", av, DESC + x * DSIZE + 8)[0] not in RATES or struct.unpack_from("<I", av, DESC + x * DSIZE + 4)[0]]
        assert not others, f"profile key {key} is also used by descriptors outside the design: {others}"
        po = prof_off[key][0]
        assert struct.unpack_from("<HH", av, po + 4) == (W, H0) and struct.unpack_from("<II", av, po + 0x34) == (W, H0), key
        d.add("av-cam.bin", av, "A2-profile", po + 6, struct.pack("<H", H1), f"profile key {key}: raster height +0x06 -> 2560", struct.pack("<H", H0))
        d.add("av-cam.bin", av, "A2-profile", po + 0x38, struct.pack("<I", H1), f"profile key {key}: raster height +0x38 -> 2560", struct.pack("<I", H0))
        if struct.unpack_from("<HH", av, po + 0x8A) == (W, H0):
            d.add("av-cam.bin", av, "A2-profile", po + 0x8C, struct.pack("<H", H1), f"profile key {key}: raster height +0x8c -> 2560", struct.pack("<H", H0))
        split = struct.unpack_from("<H", av, po + 0x56)[0]
        if split:
            assert split in (1072, 1088), (key, split)
            d.add("av-cam.bin", av, "A2-profile", po + 0x56, struct.pack("<H", H1 // 2),
                  f"profile key {key}: rows for the first core +0x56: {split} -> {H1 // 2} (half the picture; a multiple of 16 and of 64)", struct.pack("<H", split))
        picked[-1]["level_byte"] = av[po + f["level_off"]]
        if level6:
            d.add("av-cam.bin", av, "A2-level", po + f["level_off"], bytes([f["level6"]]),
                  f"profile key {key}: level {av[po + f['level_off']]} -> {f['level6']} (Level 6, the lowest level whose picture size limit holds 3840 by 2560)")
    assert picked and {p["format"] for p in picked} == set(f["groups"].values()), picked
    # ---- av-cam: the monitoring label
    assert struct.unpack_from("<4I", av, CLIP + 0x10) == (1, 8192, 4320, CLIP_8K) and struct.unpack_from("<4I", av, CLIP + 0x50) == (1, W, H0, CLIP_4K)
    d.add("av-cam.bin", av, "A3-clip", CLIP + 0x14, struct.pack("<3I", W, H1, CLIP_4K),
          f"clip-format row 1 (8192x4320, code {CLIP_8K}; unused on this camera) -> 3840x2560, code {CLIP_4K}, the code row 5 gives a 3840x2160 recording. "
          "Row 5 is left as it is",
          struct.pack("<3I", 8192, 4320, CLIP_8K))
    return d, picked


def combine(parts):
    """The union of the family designs: one design that serves both formats. The two sites they share (the unit-type row and the clip-format row)
    must be the same bytes in each; they are taken once."""
    d = Design(f"ogfile2560_hs_s{SUFFIX}_v1", f"A 3840 by 2560 file on XAVC HS 4K and on XAVC S 4K at {rate_text()}: the union of ogfile2560_hs_v1 and ogfile2560_s_v1")
    seen = {}
    for part, _ in parts:
        for p in part.patches:
            k = (p["binary"], p["file_off"])
            if k in seen:
                assert seen[k]["old"] == p["old"] and seen[k]["new"] == p["new"] and p["kind"] in ("A0-unit", "A3-clip"), k
                continue
            seen[k] = p
            d.patches.append(p)
        d.optional += part.optional
    spans = sorted((p["binary"], int(p["file_off"], 16), len(p["new"]) // 2) for p in d.patches)
    assert all(a[0] != b[0] or a[1] + a[2] <= b[1] for a, b in zip(spans, spans[1:])), "sites of the two designs overlap"
    return d, [x for _, picked in parts for x in picked]


def main():
    if "--build" in sys.argv:
        use_build(sys.argv[sys.argv.index("--build") + 1])
    lm = locate_file.locate(BUILD, "libmpr.so").read_bytes()
    av = locate_file.locate(BUILD, "av-cam.bin").read_bytes()
    sha = {"libmpr.so": hashlib.sha256(lm).hexdigest(), "av-cam.bin": hashlib.sha256(av).hexdigest()}
    level6 = "--level6" in sys.argv
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None      # with --register: that design alone
    out_dir = ROOT / "modding" / "designs"
    built = [(fam, FAMILIES[fam]["title"], *build(fam, lm, av, level6)) for fam in FAMILIES]
    if not level6:
        built.append(("hs_s", "XAVC HS 4K (HEVC) and XAVC S 4K (AVC)", *combine([(d, picked) for _, _, d, picked in built])))
    meta_extra = {}
    if "--meta" in sys.argv:
        # 2026-11-24, at the owner's request: ogfile2560_hs_s_v2 = the union design plus the two MP4 header heights (build/mp4_meta_sites.py; the
        # optional L2-mp4 sites made real): tkhd, stsd and Sony's PROF say 3840x2560 (build/emu_mp4_meta.py). Sony's XML is unchanged.
        # 2026-11-25: also the FX3 7.02 (ogfile2560_hs_s_fx3_v2), whose writer is the A7 IV's relinked (mp4_meta_sites.OTHER_BUILDS).
        # 2026-11-25: and the FX2 1.01 (ogfile2560_hs_s_fx2_v2): its writer is the A7 IV's too (track config 0x21f364).
        # 2026-11-25: and the A7C II 2.01 (ogfile2560_hs_s_c2_v2): the A7 IV's writer moved by -0x390c (mp4_meta_sites.SHIFTED).
        # 2026-11-26: and the FX30 6.01 (ogfile2560_hs_s_fx30_v2): its writer is the FX3's, 0x2c higher (track config 0x21fef0).
        # 2026-11-26: and the A1 II 4.00 (ogfile2560_hs_s_a1m2_v2): the A7 IV's writer moved by +0x15c4 (mp4_meta_sites.SHIFTED).
        # 2026-11-26: and the A6700 2.00 (ogfile2560_hs_s_a6700_v2): its writer is another compile (track config 0x1ec14c, height in w5).
        assert not level6 and SUFFIX in ("", "_fx3", "_fx2", "_c2", "_fx30", "_a1m2", "_a6700"), "--meta: the A7 IV, FX3, FX2, A7C II, FX30, A1 II and A6700 3840x2560 union designs only"
        import mp4_meta_sites
        fam, fmt, du, picked_u = built[-1]
        dm = Design(f"ogfile2560_hs_s{SUFFIX}_v{3 if RATE30 else 2}", du.title + "; the MP4 headers (tkhd, stsd, Sony's PROF) say 3840x2560")
        dm.patches = [dict(p) for p in du.patches]
        meta = mp4_meta_sites.sites(W, H1, BUILD)
        mp4_meta_sites.check(lm, meta)
        for a, new, want, why in meta:
            dm.add("libmpr.so", lm, "L4-mp4size", a, new, why + f" (`{want[0]} {want[1]}` -> `mov`)", lm[a:a + 4], code=True)
        dm.optional = [p for p in du.optional if int(p["file_off"], 16) not in {a for a, *_ in meta}]
        g = mp4_meta_sites.guards(lm, meta)
        meta_extra[dm.name] = {"libmpr_code_guards": [{"site": hex(a), "guards": g if k == 0 else []} for k, (a, *_) in enumerate(meta)],
                               "mp4_meta": {"what": "the track config %s builds (tkhd, stsd and Sony's PROF video entry) says 3840x2560; Sony's XML "
                                                    "(NonRealTimeMeta) is unchanged: its size keys the videoCodec name lookup" % {"a7iv_602": "0x222b18", "fx3_702": "0x21fec4",
                                                                                                    "fx2_101": "0x21f364", "a7c2_201": "0x21f20c",
                                                                                                    "fx30_601": "0x21fef0", "a1m2_400": "0x2240dc",
                                                                                                    "a6700_200": "0x1ec14c"}[BUILD],
                                            "sites": [{"file_off": hex(a), "stock": f"{w[0]} {w[1]}", "note": why} for a, _, w, why in meta],
                                            "checked": {"a7iv_602": "build/emu_mp4_meta.py -> evidence/pipeline/mp4_meta_emu.json",
                                                        "fx3_702": "build/emu_mp4_meta.py --build fx3_702 -> evidence/fx3/mp4_meta_emu_fx3.json",
                                                        "fx2_101": "build/emu_mp4_meta.py --build fx2_101 -> evidence/fx2/mp4_meta_emu_fx2.json",
                                                        "a7c2_201": "build/emu_mp4_meta.py --build a7c2_201 -> evidence/a7c2/mp4_meta_emu_c2.json",
                                                        "fx30_601": "build/emu_mp4_meta.py --build fx30_601 -> evidence/fx30/encoder/mp4_meta_emu_fx30.json",
                                                        "a1m2_400": "build/emu_mp4_meta.py --build a1m2_400 -> evidence/a1m2/encoder/mp4_meta_emu_a1m2.json",
                                                        "a6700_200": "build/emu_mp4_meta.py --build a6700_200 -> evidence/a6700/encoder/mp4_meta_emu_a6700.json"}[BUILD]}}
        built.append(("hs_s", fmt, dm, picked_u))
    if RATE30:                                       # only the union design with the header heights: the v1 / v2 files keep their 24p/25p content
        assert "--meta" in sys.argv and SUFFIX == "_fx3" and not level6, "--rate30: the FX3 union design with --meta only"
        built = built[-1:]
    designs = []
    for fam, fmt, d, picked in built:
        by = {}
        for p in d.patches:
            by.setdefault(p["binary"], []).append(p)
        kinds = {}
        for p in d.patches:
            kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
        out = {"design": d.name, "title": d.title, "generated_by": "build/build_ogfile.py" + (" --level6" if level6 else ""), "family": fam,
               "format": fmt, "raster": [W, H1], "rates": sorted(RATES.values()), **({"build": BUILD} if SUFFIX else {}),
               "goes_with": "dmmwb4688_v1 + ogsq_v3 (the baseline) and outsz2560_v1 (the output size), all in coprocessor RAM",
               "artifact_sha256": sha,
               "summary": {b: {"sites": len(ps), "bytes": sum(len(p["new"]) // 2 for p in ps), "code_sites": sum(p["code"] for p in ps)} for b, ps in by.items()},
               "sites_by_kind": kinds, "level": "raised to Level 6" if level6 else "the stock level bytes are kept (HEVC 150/153, AVC 51/52 as the rows have them)",
               "while_applied": ["the format's other frame rates find no descriptor: their recordings are refused at encoder open (the request says 2,560 rows, "
                                 "their descriptors still say 2,160)", "other formats are not touched",
                                 "the container and the metadata still say 3840 by 2160"],
               "descriptors": picked, "patches": d.patches, "optional_sites": d.optional}
        if d.name in meta_extra:
            out["generated_by"] += " --meta"
            out["while_applied"][-1] = "the MP4 headers (tkhd, stsd, Sony's PROF) say 3840 by 2560 (3:2); Sony's XML in the file still says 3840x2160, 16:9"
            out.update(meta_extra[d.name])
        out_dir.mkdir(exist_ok=True)
        (out_dir / f"{d.name}.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf8", newline="\n")
        for b, ps in by.items():
            (out_dir / f"{d.name}_pokes_{b.split('.')[0].replace('-', '')}.txt").write_text("".join(f"{p['file_off']} {p['new']}\n" for p in ps), encoding="utf8",
                                                                                           newline="\n")
        print(d.name, out["summary"], kinds, "descriptors:", len(picked), "profiles:", len({p["profile_key"] for p in picked}))
        if "--list" in sys.argv:
            for p in picked:
                print("    #%d %s %s input %d class %d key %d pred %d core %d level %s" % (p["descriptor"], p["format"], p["rate"], p["input_rate"], p["quality_class"],
                                                                                        p["profile_key"], p["pred_mode"], p["use_core"], p.get("level_byte")))
        designs.append((d, sha))
    if "--register" in sys.argv:
        import records
        st = records.Store()
        names = [d.name for d, _ in designs if only in (None, d.name)]
        st.begin("designs %s: the encoder side of a 3840 by 2560 file on a stock 4K format, as patch sites" % ", ".join(names), WHY,
                 evidence="modding/designs/<name>.json from build/build_ogfile.py", author="build_ogfile.py")
        for d, sha in designs:
            if only not in (None, d.name):
                continue
            for i, p in enumerate(d.patches, 1):
                data = {"design": d.name, "design_title": d.title, "artifact": p["binary"], "artifact_sha256": sha[p["binary"]], "addr": p["va"],
                        "file_off": p["file_off"], "length": len(p["new"]) // 2, "old_hex": p["old"], "old_source": "stock file", "new_hex": p["new"],
                        "patch_kind": p["kind"], "risk_class": "R3" if p["code"] else "R2", "old_verified": True, "note": p["note"],
                        "source": f"modding/designs/{d.name}.json"}
                rid, ttl = f"PS-{d.name}-{i}", f"{d.name} {p['kind']}: {p['note']}"
                if rid in st.records:
                    st.amend(rid, data, title=ttl)
                else:
                    st.add("patch_site", ttl, data, id=rid, level="static", certainty="inferred", build=BUILD, subsystem="patch-design")
        print("registered:", st.commit(), "changes")


if __name__ == "__main__":
    main()
