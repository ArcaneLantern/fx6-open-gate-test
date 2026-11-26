"""Run a build's movie size-table set-up function alone and print the table it leaves.

  C:/Python313/python.exe -B build/emu_size_table.py <build>

A7 IV 6.02: function 0x4293c8, table at 0x143c784 (finding F673). A7S III 5.01: 0x40af34 (matched by code, see
modding/A7S3_PORT.md). Calls out of the function are skipped (they return 0), so the table shows what the
function itself stores, for each of its paths that the run takes with zeroed state. Read-only.
"""
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn import arm_const as A

ROOT = Path(__file__).resolve().parent.parent
BASE, RET = 0x108000, 0x2400000
CONSTS = {"a7iv_602": (0x4293C8, 874, 0x143C734, 0x50), "a7s3_501": (0x40AF34, 904, 0x13EC260, 0x4C),
          "a7c2_201": (0x4B7354, 922, 0x1A53130, 0x50),   # A7C II 2.01: matched by match_seed + diff_consts (2026-11-24); one class more than the A7 IV (8192x4320 is class 1)
          "zve1_202": (0x4AADD8, 922, 0x19964C4, 0x50),   # ZV-E1 2.02: match_seed / match_thumb from the A7C II's 0x4b7354 (135 votes; exact masked match), diff_consts 318 of 324 aligned, same length
          "fx3_702": (0x4008EC, 904, 0x13C3144, 0x4C),     # FX3 7.02: the A7S III's 0x40af34 relinked (294 instructions, 26 differ, all relocated BL/branch/MOVW/MOVT)
          "fx6_602": (0x40793C, 904, 0x1626B30, 0x4C),     # FX6 6.02 (2026-11-26): the FX3's 0x4008ec relinked (match_thumb exact; diff_consts 283 of 294 aligned, only relocated targets/addresses differ)
          # FX2 1.01 (2026-11-25): NOT the A7C II's function relinked: 0x4ff894 (match_seed from 0x4b7354, then read: same head, three more saved
          # registers, a second settings block 0x196aa58, the fields after +0x1c moved by 4 and a 0x30-byte block cleared at +0x54), 0x42a bytes to
          # its pop at 0x4ffcbc. Its table is at base + 0x88 and holds the A7C II's 16 entries; the reader 0x51fca6 (tbh) case 3 loads base + 0xd0.
          "fx2_101": (0x4FF894, 0x42A, 0x18F6028, 0x88),
          # FX30 6.01 (2026-11-26, FX30 port): the A7 IV's 0x4293c8 at 0x4644bc (match_thumb exact; diff_consts 275 of 283 aligned: relocated
          # targets, the base 0x143c734 -> 0x155d3bc and the fields after +0x120 4 bytes earlier), 0x37e bytes to its pop at 0x464838.
          # Its table is at base + 0x50 as on the A7 IV, with the A7 IV's 16 entries; the reader's tbh 0x480a36 case 3 loads base + 0x88.
          "fx30_601": (0x4644BC, 0x37E, 0x155D3BC, 0x50),
          # A1 II 4.00 (2026-11-26, A1 II port): the FX2's 0x4ff894 at 0x501834 (match_seed 64 votes; diff_consts 305 of 342 aligned: relocated
          # targets, base 0x18f6028 -> 0x1938404, settings block 0x196aa58 -> 0x19acc14, every field from +0x88 on 4 bytes lower), 0x412 bytes to
          # its pop at 0x501c44. Table at base + 0x84 (modding/A1M2_PORT_DMM_SIZE.md).
          "a1m2_400": (0x501834, 0x412, 0x1938404, 0x84),
          # A6700 2.00 (2026-11-26, A6700 port): the ZV-E1's 0x4aadd8 (= A7C II 0x4b7354) at 0x4ab69c (match_thumb exact from both;
          # diff_consts 289 of 295 aligned: relocated targets and the base 0x19964c4 -> 0x199ec2c), the same 922 bytes to its pop at 0x4aba34.
          # Table at base + 0x50 = 0x199ec7c (modding/A6700_PORT_DMM_SIZE.md).
          "a6700_200": (0x4AB69C, 922, 0x199EC2C, 0x50)}


def table(build):
    fn, size, base, off = CONSTS[build]
    img = next(p for p in (ROOT / "work/extracted" / build).rglob("cpapp-b.bin") if "nflasha8" in p.as_posix()).read_bytes()
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    uc.mem_map(0x100000, 0x2500000)
    uc.mem_write(BASE, img)
    writes = []

    def on_code(u, addr, sz, _):
        if addr == RET:
            u.emu_stop()
        elif not fn <= addr < fn + size:
            u.reg_write(A.UC_ARM_REG_R0, 0)
            u.reg_write(A.UC_ARM_REG_PC, u.reg_read(A.UC_ARM_REG_LR))

    uc.hook_add(UC_HOOK_CODE, on_code)
    uc.hook_add(UC_HOOK_MEM_WRITE, lambda u, acc, addr, sz, val, _: writes.append((addr, sz, val)) if base <= addr < base + 0x400 else None)
    uc.reg_write(A.UC_ARM_REG_SP, 0x2300000)
    uc.reg_write(A.UC_ARM_REG_LR, RET | 1)
    uc.emu_start(fn | 1, RET, count=200000)
    t = base + off
    rows = [struct.unpack("<HHI", bytes(uc.mem_read(t + 8 * k, 8))) for k in range(16)]
    return t, rows, writes


if __name__ == "__main__":
    t, rows, writes = table(sys.argv[1])
    print(f"table at {t:#x}; {len(writes)} stores into the block")
    for k, (w, h, mid) in enumerate(rows):
        print(f"  {t + 8 * k:#x}  class {k // 2} entry {k % 2}: {w} x {h}, memory id {mid:#x}")
