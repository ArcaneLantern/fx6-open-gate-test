"""Run a build's image-mode record selector for every drive mode and key, and return the records it hands out.

  C:\\Python313\\python.exe -B build\\emu_record_selector.py <build> [--compare a7s3_501]

The generic form of build/s3_emu_selector.py (A7S III 5.01): the same key struct {mode, 0, k8, c, d} and the same key
ranges (c, d in 0/1, k8 0..0x3f), at the build's own selector address. `records(build)` returns {mode id: sorted record
addresses other than the selector's default}. Read-only: nothing is written anywhere.

Builds:
  a7s3_501  selector 0x256128, mode ids 0xc70624 (40)   (modding/A7S3_PORT.md section 14)
  fx3_702   selector 0x2514b8, mode ids 0xc53790 (40)   (same instructions as 0x256128 but for relocated addresses; 2026-11-24)
  fx2_101   selector 0x27ab64, mode ids 0xe944b0 (32)   (the A7C II's 0x2731f8; 2026-11-25)
  a7c2_201  selector 0x2731f8, mode ids 0xde99d4 (30)
"""
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UcError
from unicorn import arm_const as A

sys.path.insert(0, str(Path(__file__).resolve().parent))
import locate_file  # noqa: E402

BASE = 0x108000
CONSTS = {"a7s3_501": {"selector": 0x256128, "ids": 0xC70624, "modes": 40},
          "fx3_702": {"selector": 0x2514B8, "ids": 0xC53790, "modes": 40},
          # FX6 6.02 (2026-11-26): the FX3's selector 0x2514b8 at 0x261d10 (match_thumb, single exact masked hit)
          "fx6_602": {"selector": 0x261D10, "ids": 0xE009FC, "modes": 40},
          # FX2 1.01 (2026-11-25): the A7C II's selector 0x2731f8 at 0x27ab64 (same compare chain; its first bound is 0x501f, the A7C II's 0x5020)
          "fx2_101": {"selector": 0x27AB64, "ids": 0xE944B0, "modes": 32},
          # FX30 6.01 (2026-11-26, FX30 port): its own compare chain at 0x73ccde (found by the MOVW/MOVT loads of its record addresses);
          # the same key struct. Modes 0x820, 0x880, 0x890, 0x8c0, 0x8d0 all get the pair 0xc79440 / 0xc79ff8
          "fx30_601": {"selector": 0x73CCDE, "ids": 0xD10D68, "modes": 31},
          # A6700 2.00 (2026-11-26, A6700 port): the FX30's compare chain 0x73ccde at 0x7938f4 (match_thumb, single exact masked hit); the same
          # 31 mode ids. Modes 0x820, 0x880, 0x890, 0x8c0, 0x8d0 all get the pair 0xd3885c / 0xd39414, mode 0x830 the pair 0xd39fcc / 0xd3ab84
          "a6700_200": {"selector": 0x7938F4, "ids": 0xDC7B5C, "modes": 31},
          # A1 II 4.00 (2026-11-26, A1 II port): compare chain at 0x279f20 (found by the MOVW/MOVT loads of its record addresses, e.g.
          # 0xdf6844 at 0x27a0b0); the same key struct
          "a1m2_400": {"selector": 0x279F20, "ids": 0xE9EB40, "modes": 44},
          # A7C II 2.01, for comparison with the FX2 (A7C II port: build/c2_emu_selector.py)
          "a7c2_201": {"selector": 0x2731F8, "ids": 0xDE99D4, "modes": 30}}
KEY, RET = 0x2400000, 0x2410000


def records(build):
    c = CONSTS[build]
    d = locate_file.locate(build, "cpapp-b.bin").read_bytes()
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    uc.mem_map(0x100000, 0x2500000)
    uc.mem_write(BASE, d)
    ids = struct.unpack_from("<%dI" % c["modes"], d, c["ids"] - BASE)

    def sel(mode, k8, cc, dd):
        uc.mem_write(KEY, struct.pack("<III", mode, 0, k8) + bytes([cc, dd, 0, 0]))
        uc.reg_write(A.UC_ARM_REG_R0, KEY)
        uc.reg_write(A.UC_ARM_REG_LR, RET | 1)
        uc.reg_write(A.UC_ARM_REG_SP, 0x2300000)
        try:
            uc.emu_start(c["selector"] | 1, RET, count=4000)
        except UcError:
            return None
        return uc.reg_read(A.UC_ARM_REG_R0)

    default = sel(0x1, 0, 0, 0)
    out = {}
    for mode in ids:
        got = set()
        for cc in (0, 1):
            for dd in (0, 1):
                for k8 in range(0x40):
                    r = sel(mode, k8, cc, dd)
                    if r is not None and r != default:
                        got.add(r)
        out[mode] = sorted(got)
    return out, default


def main():
    v = sys.argv[1:]
    build = v[0]
    recs, default = records(build)
    print(f"{build}: default record {default:#x}")
    for m, rs in recs.items():
        print(f"  {m:#06x}: {', '.join(hex(r) for r in rs) or 'none'}")
    if "--compare" in v:
        other = v[v.index("--compare") + 1]
        o, _ = records(other)
        assert list(o) == list(recs), "the mode tables differ"
        shifts = {r2 - r1 for m in recs for r1, r2 in zip(o[m], recs[m])}
        same_shape = all(len(o[m]) == len(recs[m]) for m in recs)
        print(f"against {other}: same number of records per mode: {same_shape}; address shifts: {sorted(hex(s) for s in shifts)}")


if __name__ == "__main__":
    main()
