"""Find an A7 IV 6.02 av-cam.bin function in another build's av-cam.bin by its code (2026-11-25, for the FX3 XAVC S-I port).

  C:/Python313/python.exe -B build/avcam_fnport.py fx3_702 0x21b780 0x2136c4 ...

The function's extent comes from the A7 IV index (code_a7iv_602.sqlite, table `function`). Each instruction is normalised: the targets of
B/BL/B.cond/CBZ/CBNZ/TBZ/TBNZ, the page of ADRP, a literal load's offset, and the low 12 bits that an ADD/LDR/STR adds to a register an ADRP set
within the 8 instructions before are blanked; everything else (registers, structure offsets, immediates, conditions) must be equal. A match is
reported only if the whole body is equal so, at exactly one place in the other build's code. Returns file offsets.
"""
import sqlite3
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import locate_file  # noqa: E402

AVB = 0xFFFFFFC001000000
CODE_END = 0xA00000                     # av-cam.bin's code lies below this on the A7 IV, A7S III, FX3


def _signed(v):
    return v - (1 << 64) if v >= 1 << 63 else v


def a7iv_size(off):
    """The A7 IV index's size of the function at file offset off (bytes)."""
    con = sqlite3.connect(f"file:{ROOT / 'code_a7iv_602.sqlite'}?mode=ro", uri=True)
    art = con.execute("select id from artifact_ref where name='av-cam.bin'").fetchone()[0]
    r = con.execute("select size from function where artifact=? and addr=?", (art, _signed(AVB + off))).fetchone()
    if not r or not r[0]:
        raise SystemExit("no function at %#x in the A7 IV index" % off)
    return r[0]


def normalise(words):
    out, adrp = [], {}
    for i, w in enumerate(words):
        for r in [r for r, at in adrp.items() if i - at > 8]:
            del adrp[r]
        if w & 0x7C000000 == 0x14000000:                        # B, BL
            n = w & 0xFC000000
        elif w & 0xFF000010 == 0x54000000:                      # B.cond
            n = w & 0xFF00001F
        elif w & 0x7E000000 == 0x34000000:                      # CBZ, CBNZ
            n = w & 0xFF00001F
        elif w & 0x7E000000 == 0x36000000:                      # TBZ, TBNZ
            n = w & 0xFFF8001F
        elif w & 0x9F000000 == 0x90000000:                      # ADRP
            n = w & 0x9F00001F
            adrp[w & 31] = i
        elif w & 0x9F000000 == 0x10000000:                      # ADR
            n = w & 0x9F00001F
        elif w & 0x3B000000 == 0x18000000:                      # LDR literal
            n = w & 0xFF00001F
        elif (w & 0x7F800000 == 0x11000000) and ((w >> 5) & 31) in adrp:      # ADD (imm) of an ADRP page
            n = w & 0xFFC003FF
        elif (w & 0x3B000000 == 0x39000000) and ((w >> 5) & 31) in adrp:      # LDR/STR (unsigned offset) of an ADRP page
            n = w & 0xFFC003FF
        else:
            n = w
        out.append(n)
    return tuple(out)


def port(build, offs, a7=None, other=None):
    """{A7 IV file offset: other build's file offset} for every function found once with an equal normalised body."""
    a7 = a7 or locate_file.locate("a7iv_602", "av-cam.bin").read_bytes()
    other = other or locate_file.locate(build, "av-cam.bin").read_bytes()
    n_o = CODE_END // 4
    ow = struct.unpack_from("<%dI" % n_o, other, 0)
    onorm = normalise(ow)
    first = {}
    for i in range(n_o):
        first.setdefault(onorm[i], []).append(i)
    res = {}
    for off in offs:
        size = a7iv_size(off)
        body = normalise(struct.unpack_from("<%dI" % (size // 4), a7, off))
        # the rarest instruction of the body anchors the search
        anchor = min(range(len(body)), key=lambda k: len(first.get(body[k], ())))
        hits = [i - anchor for i in first.get(body[anchor], ()) if i - anchor >= 0 and onorm[i - anchor:i - anchor + len(body)] == body]
        res[off] = (hits[0] * 4 if len(hits) == 1 else None, size, len(hits))
    return res


if __name__ == "__main__":
    b = sys.argv[1]
    for off, (got, size, n) in port(b, [int(x, 16) for x in sys.argv[2:]]).items():
        print("A7 IV %#x (%d bytes) -> %s: %s" % (off, size, b, "%#x" % got if got is not None else "not found once (%d places)" % n))
