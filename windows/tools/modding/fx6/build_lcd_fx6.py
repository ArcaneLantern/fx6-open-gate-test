"""Design lcd32_fx6_v1: the FX6 6.02 LCD shows the open-gate live view at 3:2 (pillarboxed on its 16:9 panel), and the FX6's own
De-Squeeze Display stays right for that picture.

  work\\venv\\Scripts\\python.exe -I -B build\\build_lcd_fx6.py        writes modding/designs/lcd32_fx6_v1.json

The FX6 counterpart of lcd32dsq_fx3_v1 (build/build_lcd_fx3.py). The open-gate live view is a 16:9 frame (picture aspect code 2) that holds
the whole 3:2 sensor area squeezed vertically, as on the FX3. The FX6's layout code (cpapp-b.bin 6.02, loaded at 0x108000) is the FX3's
family but in another compile (modding/FX6_PORT_SCREEN.md):

  layout 0x1db458 (FX3 0x1df884)  ->  panel code 0x60a91a -> panel-type function 0x1dba9c (FX3 0x1e0050)
                                   ->  fit mode 0x1db108 (FX3 0x1df458; tables 0x1db154 / 0x1db16c / 0x1db184)
                                   ->  picture ratio 0x1db32c (de-squeeze off) or de-squeeze calculator 0x60b2ec (on, test 0x625e28)

Why the FX3's method alone does not work here. On the FX3 (4:3 panel) a 16:9 picture gets fit mode 3 (letterbox, height = width x n/d)
and the change 9/16 -> 2/3 gives a 3:2 box. On a 16:9 panel (panel code 2) the fit function returns 0 for a 16:9 picture before it reads
any table (panel code == picture code), so the ratio is never used. The fit tables do have a pillarbox mode, 2 (width = height x d/n,
centred): a 16:9 picture gets it on panel code 5 (the 17:9 output: fit table 0x1db154 row [3, 3, 0, 0, 0, 2]). So:

(a) Panel code of the LCD: the panel-type function maps the rear panel-type byte (RAM 0x1703944, the FX3's 0x14909e4) through table
    0x1dbb40 [0xff, 1, 0, 2] to an index into 0xce4ee8 [0, 2, 1, 0, 1, 2, 3, 4, 5, ...]. Type 1 (16:9) -> index 1 -> code 2. The word
    0x1dbb44 (type 1's index) 1 -> 8: 0xce4ee8[8] = 5 (0xce4ef4 is an identity table from index 3 on). Only devices 1 (rear) and 2 read
    table 0x1dbb40; HDMI (device 4) and the 0x40/0x80 outputs compute their own codes, device 0x20 uses table 0x1dbb34.
    Panel code 5 differs from 2 only in the fit mode, and the fit mode only in two cases (fit tables, read here):
      16:9 picture  0 (fill) -> 2 (pillarbox): wanted; with the stock 9/16 the pillarbox of a 16:9 picture on a 16:9 panel is the
                    whole panel, so this word alone changes nothing that is shown
      17:9 picture  3 (letterbox 135/256) -> 0 (fill): a DCI live view fills the LCD (6% taller) while the step is applied
    The panel code feeds nothing else: 0x60a91a's callers are the two layouts (0x1db458, 0x60af6e) and the HDMI rectangle 0x60c9a8
    (device 4 only), and in the two layouts it reaches only the fit function (the ratio function and the de-squeeze calculator ignore it).
(b) The picture-ratio function's 16:9 case (0x1db34e movs r0, #9; 0x1db350 movs r2, #0x10) -> 2 / 3, the function's own 3:2 case. Fit 2
    on 1280 x 720 then gives (100, 0, 1080, 720); fit 3 on a 4:3 or 3:2 panel gives the FX3's 3:2 letterbox (the step works whatever
    panel type the FX6 reports).
(c) The De-Squeeze Display (VdfInputCmdSetDeSqueeze 0x606e46 accepts codes 0, 1, 2, 4; appFw offers Off / 1.3x / 2.0x). The calculator
    0x60b2ec: full width, centred, height = (width x n + 2d) / d & ~3, n/d by code and picture shape. For a 3:2 picture:
      code 1 (1.3x), 16:9 picture   0x60b35c / 0x60b360  45/104 -> 20/39   (shown 1.95:1)
      code 4 (2.0x), every shape,   0x60b354 / 0x60b358   3/8   ->  1/3    (3:1, the whole 3:2 frame: the owner's FX3 choice)
        and code 2 with a 16:9 picture (the same instructions)
    and the 2.0x centre crop is turned off: 0x60cf1e crops the input to a centre 4:3 (width = (4h + 6) / 3) when the code is 4; its one
    compare 0x60cf42 `cmp r0, #4` -> `cmp r0, #5` (the VDF command refuses 3 and anything above 4, so 5 is never stored).
    The 17:9 ratios (code 1 0x60b324/0x60b328, code 2 0x60b336/0x60b33a) stay stock.

There is no frame-table part: the FX6 has neither the FX3's frame-widget tables (cpActAfWindowRemoteSend is gone) nor its frame check
(no 640.0 / 480.0 doubles, no `vmov.f64 d1, #5.0`). The FX6's second layout 0x60af6e (another plane of the same device) goes through
the same panel code, fit and ratio functions, so a plane whose picture code is 2 is laid out at the same 3:2 box.

While applied: every 16:9 picture on the LCD (and on device 2 when its type byte is 1) is shown at 3:2 pillarboxed; a 17:9 picture fills
the LCD; the de-squeeze ratios are those of a 3:2 picture on every output that shows de-squeeze (HDMI too, the calculator is shared). The
HDMI and 0x40/0x80 outputs keep their panel codes: a 16:9 output fills as stock; a 4096-wide output (code 5) pillarboxes a 16:9 picture
at 3:2 instead of 16:9. Nothing here talks to a camera. Checked by build/emu_lcd_fx6.py (Unicorn, the FX6's own functions).
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import locate_file  # noqa: E402

NAME = "lcd32_fx6_v1"
B = 0x108000
FX = locate_file.locate("fx6_602", "cpapp-b.bin").read_bytes()
F3 = locate_file.locate("fx3_702", "cpapp-b.bin").read_bytes()
SHA = "b432af7212a4"                                   # prefix; the full hash is checked in check_context()
MD = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
fx = lambda a, n: FX[a - B:a - B + n]

LAYOUT, PANEL_CODE, PANEL_TYPE, FIT_FN, RATIO_FN, DSQ_FN, DSQ_ON, CROP_FN, VDF_DSQ = (0x1DB458, 0x60A91A, 0x1DBA9C, 0x1DB108, 0x1DB32C,
                                                                                    0x60B2EC, 0x625E28, 0x60CF1E, 0x606E46)
REAR_TYPE, SECOND_TYPE = 0x1703944, 0x1703A74          # the panel-type bytes read by 0x5f09e4 / 0x5f09f6 ([0x1703928 + 0x1c], [0x1703a58 + 0x1c])
TYPE_TABLE, CODE_TABLE = 0x1DBB40, 0xCE4EE8
PANEL_WORD = (TYPE_TABLE + 4, 1, 8)                    # type 1's index: 1 (code 2) -> 8 (code 5)
# (address, stock instruction, new instruction, what)
CODE = [(0x1DB34E, ("movs", "r0, #9"), ("movs", "r0, #2"), "picture-ratio function, 16:9 picture: numerator 9 -> 2 (the function's 3:2 case)"),
        (0x1DB350, ("movs", "r2, #0x10"), ("movs", "r2, #3"), "picture-ratio function, 16:9 picture: denominator 16 -> 3 (pillarbox width = height x 3/2)"),
        (0x60B354, ("mov.w", "sl, #3"), ("mov.w", "sl, #1"), "de-squeeze code 4 (2.0x, every picture shape) and code 2 with a 16:9 picture: 3 -> 1"),
        (0x60B358, ("movs", "r6, #8"), ("movs", "r6, #3"), "de-squeeze 2.0x: 8 -> 3 (1/3: 3:1, the whole 3:2 frame)"),
        (0x60B35C, ("mov.w", "sl, #0x2d"), ("mov.w", "sl, #0x14"), "de-squeeze code 1 (1.3x), 16:9 picture: 45 -> 20"),
        (0x60B360, ("movs", "r6, #0x68"), ("movs", "r6, #0x27"), "de-squeeze 1.3x: 104 -> 39 (height = width x 20/39: 1.95:1)"),
        (0x60CF42, ("cmp", "r0, #4"), ("cmp", "r0, #5"), "2.0x centre crop (0x60cf1e): code 4 -> 5 (never stored: 0x606e46 refuses 3 and > 4): no crop")]
ENC = {("movs", "r0, #2"): "0220", ("movs", "r2, #3"): "0322", ("mov.w", "sl, #1"): "4ff0010a", ("movs", "r6, #3"): "0326",
       ("mov.w", "sl, #0x14"): "4ff0140a", ("movs", "r6, #0x27"): "2726", ("cmp", "r0, #5"): "0528"}


def insn(data, addr):
    i = next(MD.disasm(data, addr), None)
    return (i.mnemonic, i.op_str, i.size) if i else None


def words(a, n):
    return struct.unpack_from("<%dI" % n, FX, a - B)


def check_context():
    """Facts the design rests on, each read from the image."""
    assert hashlib.sha256(FX).hexdigest().startswith(SHA)
    # the fit function: early out when panel == picture, then a switch on the picture code; its tables
    assert [insn(fx(a, 4), a)[:2] for a in (0x1DB108, 0x1DB10A, 0x1DB10C)] == [("cmp", "r0, r1"), ("bne", "#0x1db110"), ("movs", "r0, #0")]
    assert words(0x1DB154, 6) == (3, 3, 0, 0, 0, 2)                # 16:9 picture: letterbox on codes 0/1, pillarbox on code 5
    assert words(0x1DB16C, 6) == (3, 0, 2, 0, 0, 2)                # 3:2 picture
    assert words(0x1DB184, 5) == (2, 2, 0, 0, 2)                   # 4:3 picture (indexed by code - 1)
    assert [insn(fx(a, 4), a)[:2] for a in (0x1DB146, 0x1DB148, 0x1DB14A)] == [("movs", "r1, #0"), ("cmp", "r0, #3"), ("it", "lo")]   # 17:9: letterbox below code 3
    # the ratio function: 3:2 case (2, 3), 16:9 case (9, 16), 17:9 (135, 256), fit 2 (pillarbox) and 3 (letterbox) branches
    assert [insn(fx(a, 4), a)[:2] for a in (0x1DB348, 0x1DB34A, 0x1DB34E, 0x1DB350, 0x1DB354, 0x1DB35C, 0x1DB360)] == [
        ("movs", "r0, #2"), ("movs", "r2, #3"), ("movs", "r0, #9"), ("movs", "r2, #0x10"), ("movs", "r0, #0x87"), ("cmp", "r3, #3"), ("cmp", "r3, #2")]
    # the panel-type function and its tables; 0xce4ee8 index 8 = 5; only 0x1dbad8 builds 0xce4ee8 (find_movw), 0x1dc84e / 0x1dc8da build 0xce4ef4
    assert [insn(fx(a, 4), a)[:2] for a in (0x1DBAD2, 0x1DBAD4, 0x1DBAD8, 0x1DBADC, 0x1DBAE0)] == [
        ("adr", "r1, #0x6c"), ("ldr.w", "r0, [r1, r0, lsl #2]"), ("movw", "r1, #0x4ee8"), ("movt", "r1, #0xce"), ("ldr.w", "r0, [r1, r0, lsl #2]")]
    assert words(TYPE_TABLE, 4) == (0xFF, 1, 0, 2) and words(TYPE_TABLE - 12, 3) == (0xFF, 1, 0)
    assert words(CODE_TABLE, 9) == (0, 2, 1, 0, 1, 2, 3, 4, 5)
    # the rear and the second panel-type bytes (0x5f09e4 clamps >= 4 to 1, 0x5f09f6 clamps >= 2 to 2)
    for fn, base, clamp in ((0x5F09E4, REAR_TYPE - 0x1C, ("cmp", "r0, #4")), (0x5F09F6, SECOND_TYPE - 0x1C, ("cmp", "r0, #2"))):
        got = [insn(fx(a, 4), a)[:2] for a in (fn, fn + 4, fn + 8, fn + 10)]
        assert got == [("movw", "r0, #%#x" % (base & 0xFFFF)), ("movt", "r0, #%#x" % (base >> 16)), ("ldrb", "r0, [r0, #0x1c]"), clamp], got
    # the panel-code getter: devices 1, 2, 4, 32 -> 0x1dba9c, 0x40 / 0x80 -> 0x1db7f4, others -> 2
    assert insn(fx(0x60A930, 4), 0x60A930)[:2] == ("b.w", "#0x1dba9c") and insn(fx(0x60A93E, 4), 0x60A93E)[:2] == ("b.w", "#0x1db7f4")
    # the layout's auto path calls fit, then the de-squeeze test, then the calculator or the ratio function
    assert [insn(fx(a, 4), a)[:2] for a in (0x1DB66E, 0x1DB67E, 0x1DB698, 0x1DB6AC)] == [
        ("bl", "#0x1db108"), ("bl", "#0x625e28"), ("bl", "#0x60b2ec"), ("bl", "#0x1db32c")]
    # the de-squeeze calculator's code switch: 4 -> 0x60b354, 2 -> 16:9 0x60b354 / 17:9 0x60b336, 1 -> 16:9 0x60b35c / 17:9 0x60b324
    assert [insn(fx(a, 4), a)[:2] for a in (0x60B310, 0x60B312, 0x60B314, 0x60B318, 0x60B31C, 0x60B31E, 0x60B32E, 0x60B330)] == [
        ("cmp", "r0, #4"), ("beq", "#0x60b354"), ("cmp", "r0, #2"), ("cmp", "r0, #1"), ("cmp", "r6, #2"), ("beq", "#0x60b35c"), ("cmp", "r6, #2"), ("beq", "#0x60b354")]
    # VdfInputCmdSetDeSqueeze's check: code <= 4 and != 3
    assert [insn(fx(a, 4), a)[:2] for a in (0x606E58, 0x606E5A, 0x606E5C, 0x606E5E)] == [("cmp", "r1, #4"), ("bhi", "#0x606e74"), ("cmp", "r1, #3"), ("beq", "#0x606e74")]
    # the crop function: de-squeeze test, the code, one compare with 4, then the 4:3 crop
    assert [insn(fx(a, 4), a)[:2] for a in (0x60CF2E, 0x60CF40, 0x60CF42, 0x60CF44)] == [("bl", "#0x625e28"), ("ldrb", "r0, [r0]"), ("cmp", "r0, #4"), ("bne", "#0x60cfb0")]
    # the FX6 has no FX3 frame check / frame-widget tables
    assert FX.count(bytes.fromhex("b1ee041b")) == 0 and FX.count(struct.pack("<dd", 480.0, 640.0)) == 0 and FX.count(b"cpActAfWindowRemoteSend") == 0
    assert F3.count(bytes.fromhex("b1ee041b")) == 2


def design():
    check_context()
    sites, wd = [], {}
    for a, old, new, what in CODE:
        got = insn(fx(a, 4), a)
        assert got[:2] == old, (hex(a), got, old)
        enc = bytes.fromhex(ENC[new])
        assert len(enc) == got[2] and insn(enc + b"\x00\x00", a)[:2] == new, (hex(a), new)
        w = a & ~3
        cur = bytearray(wd.get(w, fx(w, 4)))
        cur[a - w:a - w + len(enc)] = enc
        wd[w] = bytes(cur)
        wd.setdefault(("what", w), []).append(what)
    a, o, n = PANEL_WORD
    assert words(a, 1) == (o,) and words(CODE_TABLE + 4 * n, 1) == (5,)
    wd[a] = struct.pack("<I", n)
    wd[("what", a)] = ["panel-type table 0x1dbb40 (devices 1 and 2), type 1 (a 16:9 panel): index 1 (panel code 2) -> 8 (0xce4ee8[8] = panel code 5, "
                       "whose fit for a 16:9 picture is 2 = pillarbox)"]
    for w in sorted(k for k in wd if isinstance(k, int)):
        sites.append({"ram_address": hex(w), "old": fx(w, 4).hex(), "new": wd[w].hex(), "note": "; ".join(wd[("what", w)])})
    G = lambda a, n, note: {"ram_address": hex(a), "bytes": fx(a, n).hex(), "note": note + ", as in the file"}
    guards = [G(0x1DB108, 12, "the fit function 0x1db108: early out when panel == picture, then the switch"),
              G(0x1DB154, 16, "fit table of a 16:9 picture, codes 0-3: 3, 3, 0, 0"),
              G(0x1DB164, 8, "fit table of a 16:9 picture, codes 4-5: 0, 2 (code 5 = pillarbox: what the panel word relies on)"),
              G(0x1DB16C, 16, "fit table of a 3:2 picture, codes 0-3"),
              G(0x1DB184, 16, "fit table of a 4:3 picture, codes 1-4"),
              G(RATIO_FN, 16, "first 16 bytes of the picture-ratio function 0x1db32c"),
              G(0x1DB33C, 16, "the ratio function's case table and its own 3:2 case (2, 3)"),
              G(0x1DB354, 16, "the ratio function after the 16:9 case: 17:9 (135/256), the fit 3 / fit 2 dispatch"),
              G(0x1DB364, 16, "the ratio function's pillarbox (fit 2): width = (height << 8) / n x d >> 8"),
              G(PANEL_TYPE + 4, 16, "the panel-type function 0x1dba9c from its fourth byte (device tests)"),
              G(0x1DBACC, 16, "the panel-type function's table lookups (adr 0x1dbb40, movw/movt 0xce4ee8)"),
              G(0x1DBB34, 12, "panel-type table of device 0x20 [0xff, 1, 0] (left alone)"),
              G(TYPE_TABLE, 4, "panel-type table 0x1dbb40, type 0 (no panel): 0xff"),
              G(TYPE_TABLE + 8, 8, "panel-type table 0x1dbb40, types 2 (4:3) and 3 (3:2): indices 0, 2"),
              G(CODE_TABLE, 16, "panel-code table 0xce4ee8, indices 0-3"),
              G(CODE_TABLE + 16, 16, "panel-code table 0xce4ee8, indices 4-7"),
              G(CODE_TABLE + 32, 4, "panel-code table 0xce4ee8, index 8 = 5 (the index the panel word selects)"),
              G(PANEL_CODE + 2, 16, "the panel-code getter 0x60a91a from its third byte (device mask 0x8000000b)"),
              G(0x1DB664, 12, "the layout's fit call (0x1db66e bl 0x1db108)"),
              G(DSQ_FN + 4, 16, "the de-squeeze calculator 0x60b2ec from its fifth byte"),
              G(0x60B300, 16, "the calculator's read of the de-squeeze code (slot 0x708) and the code-4 test"),
              G(0x60B310, 16, "the calculator's code switch (4, 2, 1) and the 1.3x 16:9 test"),
              G(0x60B320, 16, "the 1.3x 17:9 ratio (675/1664, left alone) and the code-2 16:9 test"),
              G(0x60B330, 16, "the 1.5x 17:9 ratio (45/128, left alone) and the full-picture fall-through"),
              G(0x60B364, 16, "the calculator's height calculation after the ratios"),
              G(CROP_FN + 2, 16, "first bytes of the 2.0x crop function 0x60cf1e"),
              G(0x60CF30, 16, "the crop function's de-squeeze test and its read of the code"),
              G(0x60CF44, 16, "the crop function after the code compare (device-4 test)"),
              G(0x60CF80, 16, "the crop function's 4:3 crop: width = (4h + 6) / 3"),
              G(VDF_DSQ + 2, 16, "VdfInputCmdSetDeSqueeze's check 0x606e46: code <= 4, != 3")]
    # sites are aligned words of the file; guards are aligned, at most 16 bytes, and do not overlap a site or each other
    spans = sorted([(int(s["ram_address"], 16), 4, "s") for s in sites] + [(int(g["ram_address"], 16), len(g["bytes"]) // 2, "g") for g in guards])
    assert all(a + n <= b for (a, n, _), (b, _, _) in zip(spans, spans[1:])), "a guard overlaps a site or a guard"
    assert all(int(g["ram_address"], 16) % 4 == 0 and 0 < len(g["bytes"]) // 2 <= 16 and len(g["bytes"]) % 8 == 0 for g in guards)
    assert all(int(s["ram_address"], 16) % 4 == 0 and fx(int(s["ram_address"], 16), 4) == bytes.fromhex(s["old"]) and s["old"] != s["new"] for s in sites)
    assert len(sites) == 8, len(sites)
    return {"design": NAME, "build": "fx6_602", "camera": "ILME-FX6 (FX6), firmware 6.02",
            "title": "FX6 6.02: the LCD shows the open-gate live view at 3:2, pillarboxed on the 16:9 panel (panel type 1 -> panel code 5, whose fit for a "
                     "16:9 picture is pillarbox; 16:9 picture ratio 9/16 -> 2/3), and the built-in De-Squeeze Display ratios set for a 3:2 picture "
                     "(1.3x 1.95:1, 2.0x the whole frame at 3:1, centre crop off)",
            "kind": "ram_words", "artifact": "cpapp-b.bin 6.02 (ILME-FX6), its loaded image in coprocessor RAM: the words are in the file, the change is made in RAM only",
            "artifact_sha256": hashlib.sha256(FX).hexdigest(), "generated_by": "build/build_lcd_fx6.py",
            "ported_from": "lcd32dsq_fx3_v1 (FX3 7.02; its open-gate screen step works on that camera, 2026-11-24): the same 2/3 ratio and de-squeeze "
                           "ratios; the FX6's 16:9 panel needs the pillarbox fit mode (panel word, new); no frame tables (the FX6 has none)",
            "summary": {"sites": len(sites), "bytes": 4 * len(sites), "guards": len(guards),
                        "picture": "16:9 live view (aspect code 2) holding the whole 3:2 sensor area",
                        "panel": "rear panel-type byte RAM 0x1703944 (type 1 = 16:9 expected; 2 = 4:3, 3 = 3:2 also handled)",
                        "panel_code_new": {"type 1 (16:9)": "2 -> 5 (pillarbox)", "type 2 (4:3)": "0 (letterbox, as the FX3)", "type 3 (3:2)": "1 (whole panel)"},
                        "ratio_stock": "9/16", "ratio_new": "2/3", "lcd_1280x720": [100, 0, 1080, 720],
                        "desqueeze": {"1.3x (code 1)": "45/104 -> 20/39", "2.0x (code 4) and code 2 with 16:9": "3/8 -> 1/3, centre crop off"},
                        "goes_with": ["ogsq_fx6_v1", "outsz2560_fx6_v1", "the FX6 encoder step"]},
            "while_applied": "every 16:9 picture on the LCD is shown at 3:2, pillarboxed (black bars left and right); a 17:9 (DCI) picture fills the LCD "
                             "(6% taller than true) instead of its letterbox; the de-squeeze ratios are those of a 3:2 picture on every output that "
                             "de-squeezes (the calculator is shared, HDMI's de-squeeze too), and 2.0x shows any picture at 3:1. HDMI and the 0x40/0x80 "
                             "outputs keep their own panel codes: on a 16:9 output nothing changes; on a 4096-wide output (code 5) a 16:9 picture is "
                             "pillarboxed at 3:2 instead of 16:9",
            "not_checked": ["on a camera: nothing of this design has run on an FX6",
                            "the FX6's rear panel-type byte 0x1703944 (expected 1 = 16:9 from Sony's 2.76M-dot 16:9 LCD; the dump reads it); the "
                            "display timing table (0xecf1f2) is the FX3's byte for byte, so it does not name the panel",
                            "which code the FX6 menu's 2.0x sends (1.3x = 1 and 2.0x = 4 inferred; the design makes code 2 with a 16:9 picture 3:1 too)",
                            "whether the FX6 draws focus frames on the plane the second layout (0x60af6e) lays out, and that plane's picture code",
                            "which output device id the FX6 LCD uses (1 assumed, as on the FX3; the dump's panel pages show both types)"],
            "sites": sites, "guards": guards}


if __name__ == "__main__":
    d = design()
    out = ROOT / "modding" / "designs" / f"{NAME}.json"
    out.write_text(json.dumps(d, indent=1) + "\n", encoding="utf8", newline="\n")
    print("%s: %d sites, %d guards" % (out.name, len(d["sites"]), len(d["guards"])))
    for s in d["sites"]:
        print("  %s %s -> %s  %s" % (s["ram_address"], s["old"], s["new"], s["note"][:100]))
