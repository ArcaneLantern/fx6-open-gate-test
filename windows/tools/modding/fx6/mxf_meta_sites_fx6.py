"""The FX6 6.02 MXF picture-descriptor sites of `ogfile2560_xavc_fx6_v2` (2026-11-26, at the owner's request: the metadata fix of the FX3
kit, for the FX6's MXF files). Imported by build/build_ogfile_fx6_meta.py and build/emu_mxf_meta_fx6.py.

Where the size comes from (read, libmpr.so 6.02; code compiled without optimisation, every local on the stack):
  muxMxfAvcFilePackageSectionPictureDescriptorCreate 0x612dec (muxMxfAvcFinalize.c; called three times from muxMxfAvcHeaderMetaDataCreate
  0x60c248) writes the CDCI/MPEG picture descriptor of every XAVC (AVC) MXF file with muxMxfCommonPutTag* (0x699304 = u32 tag, 0x6993f8 =
  rational): StoredWidth 0x3203 = [fp+0x78], StoredHeight 0x3202 = [fp+0x70], SampledWidth 0x3205 = [fp+0x74], SampledHeight 0x3204 and
  DisplayHeight 0x3208 = [fp+0x6c], DisplayWidth 0x3209 = [fp+0x74], AspectRatio 0x320e = {[fp+0x40], [fp+0x44]}, VideoLineMap 0x320d from
  [fp+0x38] / [fp+0x3c].
  - widths and aspect: a switch on the muxer's horizontal code [ctx+0x170] (ctx = 0x6bdabc8; jump table 0xd728bc): 3 = 1280, 7 = 1920,
    0xb = 2048, **0x12 = 3840 (case 0x6131cc: 16:9 at 0x6131e0 / 0x6131e8)**, 0x1d = 4096 (256:135)
  - heights and line map: a switch on the vertical code [ctx+0x174]: 4 = 720, 7 = 1080 (progressive 1088/1080 or interlaced), **0xb = 2160
    (case 0x613388: `mov w0, #0x870` twice), shared by 3840 and 4096 wide**
  - both codes come from the recording format's metadata (muxMxfAvcNrtMetaInfoGet 0x60a98c, from metaNrtMetaDataGet), not from the encoder's
    size, so the encoder step's 2560 does not change them.
The HD muxer (muxMxfHdFinalize.c 0x6cc130 / 0x6ce994) and the trimming tool (TlibAvcFinalize.cpp 0xb71128) have their own writers and are
not on the XAVC recording path; they are not changed.

The sites (all code in libmpr's first segment, written by helper level 19 through /proc/self/mem as the FX3's / A7 IV's header fix is):
  A  QFHD aspect: 0x6131e0 `mov w0, #0x10` -> `mov w0, #3`, 0x6131e8 `mov w0, #9` -> `mov w0, #2`. Only format code 0x12 (3840) reaches them.
  B  the 2160-line case 0x613388..0x6133a4 (8 instructions) made width-dependent, so DCI 4096 keeps 2160:
         ldr  w1, [x29, #0x78]     ; StoredWidth set by the format case
         mov  w0, #0x870
         cmp  w1, #0xf00
         b.ne 0x61339c
         mov  w0, #0xa00
         str  w0, [x29, #0x70]     ; StoredHeight
         str  w0, [x29, #0x6c]     ; SampledHeight, DisplayHeight
         b    0x613354             ; the 1080p case's tail: line map 42, 0, then on to 0x6133cc (as the stock 2160 case does)
     w1 is free there (the next code reloads every value from the stack; 0x612db0 takes w0 only).
"""
import struct

import capstone

FUNC, FUNC_END = 0x612DEC, 0x613C34
CASE_QFHD, CASE_2160, TAIL_1080P, AFTER = 0x6131CC, 0x613388, 0x613354, 0x6133CC


def a64(word):
    return struct.pack("<I", word)


def b_to(pc, target):
    return a64(0x14000000 | (((target - pc) >> 2) & 0x3FFFFFF))


def bne_to(pc, target):
    return a64(0x54000001 | ((((target - pc) >> 2) & 0x7FFFF) << 5))


def movz_w(rd, imm):
    return a64(0x52800000 | (imm << 5) | rd)


def new_2160_case():
    """The 8 new instruction words of site B, at 0x613388."""
    pc = CASE_2160
    words = [a64(0xB9407BA1),                    # ldr w1, [x29, #0x78]
             movz_w(0, 0x870),
             a64(0x713C003F),                    # cmp w1, #0xf00
             bne_to(pc + 12, pc + 20),
             movz_w(0, 0xA00),
             a64(0xB90073A0),                    # str w0, [x29, #0x70]
             a64(0xB9006FA0),                    # str w0, [x29, #0x6c]
             b_to(pc + 28, TAIL_1080P)]
    return b"".join(words)


EXPECT_OLD = {0x6131E0: ("mov", "w0, #0x10"), 0x6131E8: ("mov", "w0, #9")}
EXPECT_2160 = [("mov", "w0, #0x870"), ("str", "w0, [x29, #0x70]"), ("mov", "w0, #0x870"), ("str", "w0, [x29, #0x6c]"),
               ("mov", "w0, #0x2a"), ("str", "w0, [x29, #0x38]"), ("str", "wzr, [x29, #0x3c]"), ("b", "#0x6133cc")]
EXPECT_TAIL = [("mov", "w0, #0x2a"), ("str", "w0, [x29, #0x38]"), ("str", "wzr, [x29, #0x3c]"), ("b", "#0x6133cc")]
WANT_NEW = ["ldr w1, [x29, #0x78]", "mov w0, #0x870", "cmp w1, #0xf00", "b.ne #0x61339c", "mov w0, #0xa00", "str w0, [x29, #0x70]",
            "str w0, [x29, #0x6c]", "b #0x613354"]


def dis(blob, at, n):
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    return [(i.mnemonic, i.op_str) for i in md.disasm(blob[at:at + 4 * n], at)]


def sites(lm):
    """[(file offset, old bytes, new bytes, why)] after checking every stock instruction this design relies on."""
    for a, want in EXPECT_OLD.items():
        assert dis(lm, a, 1) == [want], (hex(a), dis(lm, a, 1))
    # the QFHD case around the two words: widths 3840 and the stores the aspect goes to
    assert dis(lm, CASE_QFHD, 9) == [("strb", "wzr, [x29, #0x7f]"), ("mov", "w0, #0xf00"), ("str", "w0, [x29, #0x78]"), ("mov", "w0, #0xf00"),
                                     ("str", "w0, [x29, #0x74]"), ("mov", "w0, #0x10"), ("str", "w0, [x29, #0x40]"), ("mov", "w0, #9"),
                                     ("str", "w0, [x29, #0x44]")], dis(lm, CASE_QFHD, 9)
    assert dis(lm, CASE_2160, 8) == EXPECT_2160, dis(lm, CASE_2160, 8)
    assert dis(lm, TAIL_1080P, 4) == EXPECT_TAIL, dis(lm, TAIL_1080P, 4)
    new = new_2160_case()
    got = [f"{m} {o}" for m, o in dis(new_patched(lm, new), CASE_2160, 8)]
    assert got == WANT_NEW, got
    out = [(0x6131E0, lm[0x6131E0:0x6131E4], movz_w(0, 3), "MXF picture descriptor, QFHD (format code 0x12) aspect ratio numerator: 16 -> 3"),
           (0x6131E8, lm[0x6131E8:0x6131EC], movz_w(0, 2), "MXF picture descriptor, QFHD aspect ratio denominator: 9 -> 2 (3:2)")]
    for k in range(0, 32, 16):            # site B as two 16-byte entries (the helper's entries hold at most 16 bytes)
        out.append((CASE_2160 + k, lm[CASE_2160 + k:CASE_2160 + k + 16], new[k:k + 16],
                    "MXF picture descriptor, the 2160-line case made width-dependent: Stored/Sampled/Display Height 2560 when the stored width is "
                    "3840, 2160 otherwise (DCI 4096 unchanged); words %d-%d of 8" % (k // 4 + 1, k // 4 + 4)))
    return out


def new_patched(lm, new):
    b = bytearray(lm)
    b[CASE_2160:CASE_2160 + 32] = new
    return bytes(b)


def guards(lm):
    """Instructions around the sites that must be as in the file (each <= 16 bytes, none overlapping a site)."""
    g = [(CASE_QFHD, 16), (0x6131E4, 4), (0x6131EC, 4), (0x6131F0, 16), (CASE_2160 - 16, 16), (AFTER, 16), (TAIL_1080P, 16)]
    return [{"file_off": hex(a), "bytes": lm[a:a + n].hex()} for a, n in g]
