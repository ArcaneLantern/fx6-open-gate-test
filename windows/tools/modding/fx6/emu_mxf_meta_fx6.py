"""Run the FX6 6.02's own MXF picture-descriptor writer (libmpr.so muxMxfAvcFilePackageSectionPictureDescriptorCreate 0x612dec) in Unicorn,
stock and with the header sites of build/mxf_meta_sites_fx6.py, and read back the descriptor it writes.

  C:/Python313/python.exe -B build/emu_mxf_meta_fx6.py [--save]

The muxer's context (global 0x6bdabc8) is set as a recording would leave it: its first word points to the header buffer (the writer starts at
+0x14), the horizontal code +0x170 and vertical code +0x174 of the format, the frame-structure code +0x168 and the codec type +0x16c. The
writer's own KLV helpers (muxMxfCommonPutTag*, 0x6989xx-0x6996xx) run as they are; metaStreamRdd18InfoGet (0x68d448) is answered with its
failure (the writer then uses its default colour labels), and the log calls are skipped. The written local tags are parsed back.

Cases: every format code the switch knows (3 = 1280, 7 = 1920, 0xb = 2048, 0x12 = 3840, 0x1d = 4096) with the vertical codes it is used with
(4, 7 and 0xb), progressive and interlaced frame codes, both codec types; stock and patched. What must hold: QFHD (0x12, 0xb) says 3840 x 2560
and 3:2 when patched (3840 x 2160, 16:9 stock); every other case is byte-identical stock vs patched; the whole tag set is the same size.
"""
import json
import struct
import sys
from pathlib import Path

from unicorn import Uc, UcError, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import arm64_const as A

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import mxf_meta_sites_fx6 as S  # noqa: E402

LM = ROOT / "work/extracted/fx6_602/0700_part_image/dev/nflasha15/lib/libmpr.so"
CTX, BUF, STACK, RET = 0x6BDABC8, 0x20000000, 0x30000000, 0x3F000000
SEG1_VA, SEG1_OFF, SEG1_FILESZ, SEG1_MEMSZ = 0xF1C8F8, 0xF0C8F8, 0xC89F10, 0x90AFE60
PLT = (0xEC5B0, 0xF6490)
STUB_FAIL = {0x68D448: 1}                         # metaStreamRdd18InfoGet: failure -> the writer's defaults
STUB_ZERO = {0xC34C40, 0xF1630}                   # log-level query, assert/log print
TAGS = {0x3203: "StoredWidth", 0x3202: "StoredHeight", 0x3205: "SampledWidth", 0x3204: "SampledHeight", 0x3209: "DisplayWidth",
        0x3208: "DisplayHeight", 0x320E: "AspectRatio", 0x320D: "VideoLineMap", 0x320C: "FrameLayout", 0x3215: "SignalStandard"}


def image(patched):
    lm = bytearray(LM.read_bytes())
    if patched:
        for a, old, new, _ in S.sites(bytes(lm)):
            assert lm[a:a + len(old)] == old
            lm[a:a + len(new)] = new
    return bytes(lm)


_UC = {}


def machine(lm):
    """One Unicorn per image: segment 0 mapped whole, segment 1's file part mapped, its .bss pages mapped when first touched."""
    if lm in _UC:
        return _UC[lm]
    uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    uc.mem_map(0, 0xF10000)
    uc.mem_write(0, lm[:0xF0B98F + 1])
    lo = SEG1_VA & ~0xFFF
    uc.mem_map(lo, ((SEG1_VA + SEG1_FILESZ + 0xFFF) & ~0xFFF) - lo)
    uc.mem_write(SEG1_VA, lm[SEG1_OFF:SEG1_OFF + SEG1_FILESZ])
    for base, size in ((BUF, 0x100000), (STACK - 0x100000, 0x100000), (RET, 0x1000)):
        uc.mem_map(base, size)
    bss_hi = SEG1_VA + SEG1_MEMSZ

    def on_unmapped(u, access, addr, size, value, _):
        if (SEG1_VA + SEG1_FILESZ) <= addr < bss_hi:           # .bss: zero pages on demand
            u.mem_map(addr & ~0xFFF, 0x2000 if (addr & 0xFFF) + size > 0x1000 else 0x1000)
            return True
        return False

    from unicorn import UC_HOOK_MEM_UNMAPPED
    uc.hook_add(UC_HOOK_MEM_UNMAPPED, on_unmapped)
    uc.mem_map(CTX & ~0xFFF, 0x2000)
    _UC[lm] = uc
    return uc


def run(lm, horiz, vert, frame, codec):
    uc = machine(lm)
    uc.mem_write(BUF, bytes(0x100000))
    ctx = bytearray(0x400)
    struct.pack_into("<Q", ctx, 0, BUF)
    for off, v in ((0x168, frame), (0x16C, codec), (0x170, horiz), (0x174, vert), (0x144, 1000)):
        struct.pack_into("<I", ctx, off, v)
    uc.mem_write(CTX, bytes(ctx))
    state = {"bad": None, "plt": set()}

    def on_code(u, addr, size, _):
        if addr == RET:
            u.emu_stop()
        elif addr in STUB_FAIL or addr in STUB_ZERO or PLT[0] <= addr < PLT[1]:
            if PLT[0] <= addr < PLT[1]:
                state["plt"].add(addr)
            u.reg_write(A.UC_ARM64_REG_X0, STUB_FAIL.get(addr, 0))
            u.reg_write(A.UC_ARM64_REG_PC, u.reg_read(A.UC_ARM64_REG_X30))

    h = uc.hook_add(UC_HOOK_CODE, on_code)
    uc.reg_write(A.UC_ARM64_REG_SP, STACK - 0x1000)
    uc.reg_write(A.UC_ARM64_REG_X30, RET)
    for r, v in ((A.UC_ARM64_REG_X0, 0), (A.UC_ARM64_REG_X1, 0), (A.UC_ARM64_REG_X2, 0)):
        uc.reg_write(r, v)
    try:
        uc.emu_start(S.FUNC, RET, count=2_000_000)
    except UcError as e:
        state["bad"] = f"{e} at {uc.reg_read(A.UC_ARM64_REG_PC):#x}"
    uc.hook_del(h)
    if not state["bad"] and uc.reg_read(A.UC_ARM64_REG_PC) != RET:
        state["bad"] = "did not return"
    buf = bytes(uc.mem_read(BUF, 0x2000))
    return parse(buf), buf, state


def parse(buf):
    """The local tags written after the 0x14-byte set header, up to the first all-zero tag."""
    o, out = 0x14, {}
    while o + 4 <= len(buf):
        tag, ln = struct.unpack_from(">HH", buf, o)
        if tag == 0 or ln > 0x200:
            break
        val = buf[o + 4:o + 4 + ln]
        name = TAGS.get(tag)
        if name:
            if tag == 0x320E:
                out[name] = "%d/%d" % struct.unpack(">ii", val)
            elif ln == 4:
                out[name] = struct.unpack(">I", val)[0]
            elif ln == 1:
                out[name] = val[0]
            else:
                out[name] = val.hex()
        o += 4 + ln
    out["_set_bytes"] = o
    return out


def main():
    stock, patched = image(False), image(True)
    cases = []
    formats = [(3, 4), (7, 7), (0xB, 7), (0x12, 0xB), (0x1D, 0xB)]
    for horiz, vert in formats:
        for frame in (0xC, 0xE, 7):                  # 7 is an interlaced code (0x612db0)
            for codec in (4, 2):
                cases.append((horiz, vert, frame, codec))
    results, ok = [], True
    for c in cases:
        (s, sbuf, ss), (p, pbuf, ps) = run(stock, *c), run(patched, *c)
        qfhd = c[0] == 0x12 and c[1] == 0xB
        # Sony's own fall-through: the 2048 case (0xb) with codec type != 4 runs on into the 3840 case (stock writes width 3840 for it). The FX6
        # has no 2048-wide AVC format (no 2048 comb row, no codec 5/8 descriptor at 2048), so this path is not reached by its XAVC recordings;
        # there the design changes the aspect only (16/9 -> 3/2) and nothing else.
        fallthrough = c[0] == 0xB and c[3] != 4
        if ss["bad"] or ps["bad"]:
            good = False
        elif fallthrough:
            strip = lambda d: {k: v for k, v in d.items() if k != "AspectRatio"}
            good = s.get("StoredWidth") == 3840 and s.get("AspectRatio") == "16/9" and p.get("AspectRatio") == "3/2" and strip(s) == strip(p)
        elif qfhd:
            want_s = (3840, 2160, "16/9")
            want_p = (3840, 2560, "3/2")
            got = lambda d: (d.get("StoredWidth"), d.get("StoredHeight"), d.get("AspectRatio"))
            good = (got(s) == want_s and got(p) == want_p and s.get("SampledHeight") == s.get("DisplayHeight") == 2160
                    and p.get("SampledHeight") == p.get("DisplayHeight") == 2560 and s["_set_bytes"] == p["_set_bytes"]
                    and {k: v for k, v in s.items() if k not in ("StoredHeight", "SampledHeight", "DisplayHeight", "AspectRatio")}
                    == {k: v for k, v in p.items() if k not in ("StoredHeight", "SampledHeight", "DisplayHeight", "AspectRatio")})
        else:
            good = sbuf == pbuf
        ok &= good
        row = {"horizontal": hex(c[0]), "vertical": hex(c[1]), "frame": hex(c[2]), "codec": c[3], "stock": s, "patched": p,
               "same_bytes": sbuf == pbuf, "ok": good, "errors": [ss["bad"], ps["bad"]]}
        results.append(row)
        print(f"{'ok  ' if good else 'FAIL'} fmt {c[0]:#x} vert {c[1]:#x} frame {c[2]:#x} codec {c[3]}: stock {s.get('StoredWidth')}x{s.get('StoredHeight')} "
              f"{s.get('AspectRatio')} -> patched {p.get('StoredWidth')}x{p.get('StoredHeight')} {p.get('AspectRatio')}"
              f"{' (byte-identical)' if sbuf == pbuf else ''}{'  ' + str(ss['bad'] or ps['bad']) if ss['bad'] or ps['bad'] else ''}")
    print("ALL PASS" if ok else "FAILED")
    if "--save" in sys.argv:
        dst = ROOT / "evidence/fx6/mxf_meta_emu_fx6.json"
        dst.write_text(json.dumps({"script": "build/emu_mxf_meta_fx6.py", "function": hex(S.FUNC), "cases": results, "all_pass": ok}, indent=1) + "\n",
                       encoding="utf8", newline="\n")
        print("wrote", dst)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
