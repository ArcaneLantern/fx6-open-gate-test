"""Run the coprocessor's own DMM server code on the real configuration stream, alone (cpapp-b.bin 6.02, Unicorn).

No operating system, no hardware, one CPU: the server's set-up 0xaffbba (which parses the stream with 0xaff040 and
0xb00c86) and its message handlers for "open" (command 0x20, 0xafc660) and "free" (command 0x23, 0xafcadc) are called
as plain functions with hand-built request blocks. This answers what the allocator does, not what the camera asks of it.

What is the firmware's own: every instruction between 0xafc000 and 0xb01400 (the DMM module) and the memory helpers it
calls (0x585f00-0x586800). What is made up: the stream reader dmm_module_GetConfigData 0x505338 is replaced by a copy from
the file (the real one finds the stream through a Backup item); every other call that leaves the module returns 0 and
is listed in the output ("outside_calls": logging, error-code conversion), and so does the module's per-handle command
history 0xaff468, whose buffers are set up elsewhere; the workspace is a block of zeroed memory at
0x2800008 (where the camera's is, is not known).

  C:\\Python313\\python.exe build\\emu_dmm_server.py PLAN [--size KEY:GROUP:SIZE,...] [--size-in stream|ram] [--limit GROUP:N,...]
        [--drop KEY:GROUP,...] [--scene N] [--out NAME]
  PLAN   comma-separated steps: open:ID   free:N (the handle of open number N, counted from 0)   dump   size:KEY:GROUP:SIZE
         limit:GROUP:N   drop:KEY:GROUP    (the last three change the firmware's RAM copy at that point of the plan)
  --size      unit-record sizes changed before the plan runs: in the firmware's RAM copy after its set-up (default, what a
              memory-only write does) or in the stream before set-up (--size-in stream, what a changed DmmCfg.bin does)
  --limit     set all 64 per-scene limit bytes of a group in the RAM copy (0 = the layout is never chosen)
  --drop      in the RAM copy, give the unit records of KEY in GROUP a key nothing asks for (0x8fe), so that layout no
              longer offers KEY
  --selfcheck the firmware's RAM copy after its own parse equals build/parse_dmmcfg.py's reading of the file
  --build B   another build's cpapp-b.bin and DmmCfg.bin (default a7iv_602; OTHER_BUILDS lists the others)
Writes evidence/hardware/dmm_server_<NAME>.json when --out is given; always prints the result.
"""
import argparse
import json
import struct
import sys
from pathlib import Path

from unicorn import Uc, UcError, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import arm_const as A

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import parse_dmmcfg  # noqa: E402

BASE = 0x108000
BUILD = "a7iv_602"
MOD = (0xAFC000, 0xB01400)                    # the DMM module
HELP = (0x585F00, 0x586800)                   # memcpy 0x585fb8, memset 0x58669c, memclr 0x5866ac and their bodies
GETCFG, INIT, OPEN, FREE = 0x505338, 0xAFFBBA, 0xAFC660, 0xAFCADC
FATAL = (0xAFEEE4, 0xAFEF2E)
SKIP = (0xAFF468,)                            # the per-handle command history; its buffers are set up outside the code run here
G_UNITS, G_WS = 0x1472610, 0x1472ABC          # the server's pointers to its unit objects and to its workspace
RAM_END = 0x2400000                           # end of the zero-initialised data mapped for the run
# Other builds (2026-11-24, A7C II port): the module, the helpers and the globals each moved as one block. Found with
# match_thumb.py / match_seed.py (every function of the module at +0x11e75a, the helpers at +0x98654, GETCFG 0x59e044 by
# match_thumb) and diff_consts.py (globals +0x619a9c). parse_dmmcfg.RAM holds the record copies.
_DEFAULTS = (BUILD, MOD, HELP, GETCFG, INIT, OPEN, FREE, FATAL, SKIP, G_UNITS, G_WS, RAM_END)
OTHER_BUILDS = {"a7c2_201": {"mod": 0x11E75A, "help": 0x98654, "getcfg": 0x59E044, "glob": 0x619A9C, "ram_end": 0x2700000},
                # ZV-E1 2.02 (2026-11-24, after the first camera test): the A7C II's module at -0x1f738 (match_thumb: 0xbfebdc set-up, 0xbfb682 open,
                # 0xbfbafe free, 0xbfe062 / 0xbffca8 readers, one hit each), GETCFG 0x591fdc (match_thumb), helpers memcpy 0x612668 / memset 0x612d4c
                # (the readers' blx), globals at A7C II -0xbcc68 (diff_consts on the set-up: workspace pointer 0x1a8c558 -> 0x19cf8f0)
                "zve1_202": {"mod": 0xFF022, "help": 0x8C6B0, "getcfg": 0x591FDC, "glob": 0x55CE34, "ram_end": 0x2700000},
                # A6700 2.00 (2026-11-26, A6700 port): the ZV-E1's module moved as one block, +0x2f46 (match_thumb zve1_202 -> a6700_200, one hit
                # each: set-up 0xbfebdc -> 0xc01b22, open 0xbfb682 -> 0xbfe5c8, free 0xbfbafe -> 0xbfea44, readers 0xbfe062 -> 0xc00fa8 /
                # 0xbffca8 -> 0xc02bee), GETCFG 0x591fdc -> 0x591f04 (match_thumb), helpers ZV-E1 - 0x428 (the set-up's blx 0x612d5c -> 0x612934),
                # globals ZV-E1 + 0x8768 (diff_consts on the set-up: workspace pointer 0x19cf8f0 -> 0x19d8058; unit objects 0x19d7bac)
                "a6700_200": {"mod": 0x101F68, "help": 0x8C288, "getcfg": 0x591F04, "glob": 0x56559C, "ram_end": 0x2700000},
                # FX2 1.01 (2026-11-25, FX2 port): the module did NOT move as one block (the A7C II's functions sit 0x9c7b2..0x9ca7c further on),
                # so every address is given. match_thumb a7c2_201 -> fx2_101, one hit each: set-up 0xc1e314 -> 0xcbab10, open 0xc1adba -> 0xcb7598,
                # free 0xc1b236 -> 0xcb7a28, readers 0xc1d79a -> 0xcb9f96 / 0xc1f3e0 -> 0xcbbe5c, history 0xc1dbc2 -> 0xcba3be, GETCFG 0x59e044 ->
                # 0x5ee620; module bounds 0xc1a75a -> 0xcb6f14 and 0xc1fb5a -> 0xcbc5da; helpers (match_seed, 155 votes) A7C II + 0x50d7c (memset
                # 0x66fa7c is the readers' blx). The readers call three byte-identical fatal reporters 0xcb9df0 / 0xcb9e3a / 0xcb9e84 (the A7C II's
                # two are 0xc1d63e / 0xc1d688). Globals: diff_consts on the set-up and open, A7C II - 0x15c930 (workspace pointer 0x1a8c558 -> 0x192fc28).
                "fx2_101": {"explicit": True, "mod_range": (0xCB6F14, 0xCBC5DA), "help_range": (0x66F2D0, 0x66FBD0), "getcfg": 0x5EE620,
                            "init": 0xCBAB10, "open": 0xCB7598, "free": 0xCB7A28, "fatal": (0xCB9DF0, 0xCB9E3A, 0xCB9E84), "skip": (0xCBA3BE,),
                            "g_units": 0x1472610 + 0x619A9C - 0x15C930, "g_ws": 0x192FC28, "ram_end": 0x2700000},
                # FX30 6.01 (2026-11-26, FX30 port): the A7 IV's module moved as one block, +0x6892e (match_thumb a7iv_602 -> fx30_601, one hit
                # each: set-up 0xaffbba -> 0xb684e8, open 0xafc660 -> 0xb64f8e, free 0xafcadc -> 0xb6540a, readers 0xaff040 -> 0xb6796e /
                # 0xb00c86 -> 0xb695b4, history 0xaff468 -> 0xb67d96, fatal reporters 0xafeee4 / 0xafef2e -> 0xb67812 / 0xb6785c, the ones the
                # readers call); GETCFG 0x505338 -> 0x53ffa0 (match_thumb); helpers +0x3aacc (0x585f00 -> 0x5c09cc, memcpy 0x5c0a84, memset
                # 0x5c1168, memclr 0x5c1178: the readers' blx); globals +0x12155c (diff_consts on the set-up and open: workspace pointer
                # 0x1472abc -> 0x1594018, 0x1472504 -> 0x1593a60)
                "fx30_601": {"mod": 0x6892E, "help": 0x3AACC, "getcfg": 0x53FFA0, "glob": 0x12155C, "ram_end": 0x2700000},
                # A1 II 4.00 (2026-11-26, A1 II port): the FX2's module, given explicitly (it did not move as one block). match_thumb fx2_101 ->
                # a1m2_400, one hit each: set-up 0xcbab10 -> 0xcb6c28, open 0xcb7598 -> 0xcb36b0, free 0xcb7a28 -> 0xcb3b40, readers 0xcb9f96 ->
                # 0xcb60ae / 0xcbbe5c -> 0xcb7ec8, history 0xcba3be -> 0xcb64d6, GETCFG 0x5ee620 -> 0x5ef784, module start 0xcb6f14 -> 0xcb302c,
                # end 0xcbc5da -> 0xcb8642 (the function 0xcbc5c4 -> 0xcb862c). The three byte-identical fatal reporters at FX2 - 0x3ee8. Helpers
                # FX2 + 0x1128 (match_seed 95 votes; memset 0x670ba4 is the readers' blx). Globals FX2 + 0x424b8 (diff_consts on the set-up and
                # open: workspace pointer 0x192fc28 -> 0x19720e0, 0x192f670 -> 0x1971b28).
                "a1m2_400": {"explicit": True, "mod_range": (0xCB302C, 0xCB8642), "help_range": (0x6703F8, 0x670CF8), "getcfg": 0x5EF784,
                             "init": 0xCB6C28, "open": 0xCB36B0, "free": 0xCB3B40, "fatal": (0xCB5F08, 0xCB5F52, 0xCB5F9C), "skip": (0xCB64D6,),
                             "g_units": 0x1472610 + 0x619A9C - 0x15C930 + 0x424B8, "g_ws": 0x19720E0, "ram_end": 0x2700000},
                # FX6 6.02 (2026-11-26, repo issue 2): the A7 IV's module, given explicitly (it did not move as one block: the functions sit
                # 0x38bea..0x38fee lower). match_thumb a7iv_602 -> fx6_602, one hit each: set-up 0xaffbba -> 0xac6ce8, open 0xafc660 -> 0xac3a62,
                # free 0xafcadc -> 0xac3ef2, readers 0xaff040 -> 0xac61a4 / 0xb00c86 -> 0xac7f7c, history 0xaff468 -> 0xac65ce, GETCFG 0x4f1b4c
                # (the one call of the module's read wrapper 0xac3980, the A7 IV's 0xafc57e -> 0x505338), module start 0xafc000 -> 0xac33f8; end 0xb01400 -> 0xac8412 (match_seed). Three byte-identical fatal reporters
                # 0xac5ffe / 0xac6048 / 0xac6092 (the readers call the last two). Helpers A7 IV - 0x13a00 (match_seed 155 votes; memclr 0x572cac
                # and memcpy 0x5725b8 are the readers' blx). Globals: diff_consts on the set-up and open, port_addr: workspace pointer
                # 0x1472abc -> 0x165ce88, unit objects 0x1472610 -> 0x165cae8 (0x1472504 -> 0x165c9dc)
                "fx6_602": {"explicit": True, "mod_range": (0xAC33F8, 0xAC8412), "help_range": (0x572500, 0x572E00), "getcfg": 0x4F1B4C,
                            "init": 0xAC6CE8, "open": 0xAC3A62, "free": 0xAC3EF2, "fatal": (0xAC5FFE, 0xAC6048, 0xAC6092), "skip": (0xAC65CE,),
                            "g_units": 0x165CAE8, "g_ws": 0x165CE88, "ram_end": 0x2700000}}


def use_build(name):
    """Point the emulator at another build's cpapp-b.bin (the A7 IV 6.02 values above are the defaults)."""
    global BUILD, MOD, HELP, GETCFG, INIT, OPEN, FREE, FATAL, SKIP, G_UNITS, G_WS, RAM_END
    (BUILD, MOD, HELP, GETCFG, INIT, OPEN, FREE, FATAL, SKIP, G_UNITS, G_WS, RAM_END) = _DEFAULTS
    if name == "a7iv_602":
        return
    b = OTHER_BUILDS[name]
    if b.get("explicit"):                         # a build whose module did not move as one block: every address given
        BUILD, MOD, HELP, GETCFG = name, b["mod_range"], b["help_range"], b["getcfg"]
        INIT, OPEN, FREE, FATAL, SKIP = b["init"], b["open"], b["free"], b["fatal"], b["skip"]
        G_UNITS, G_WS, RAM_END = b["g_units"], b["g_ws"], b["ram_end"]
        return
    m, h = b["mod"], b["help"]
    BUILD, MOD, HELP = name, (MOD[0] + m, MOD[1] + m), (HELP[0] + h, HELP[1] + h)
    GETCFG, INIT, OPEN, FREE = b["getcfg"], INIT + m, OPEN + m, FREE + m
    FATAL, SKIP = tuple(x + m for x in FATAL), tuple(x + m for x in SKIP)
    G_UNITS, G_WS, RAM_END = G_UNITS + b["glob"], G_WS + b["glob"], b["ram_end"]
STOP, WS, STK, REQ, REP, AUX = 0x0F000000, 0x02800008, 0x38000000, 0x39000000, 0x39001000, 0x39002000
WS_UNITS_AT, WS_LEN = 0x107E0, 0x35230         # the unit workspace starts this far into the server's workspace (0xaffbba); the whole is this long (0xafdac6)
ERR = {0: "ok", 0xFFFF: "refused (0xffff: no layout fits or no parent)", 0xFFFD: "unknown memory id (0xfffd)", 0xFFFC: "bad mode (0xfffc)",
       0x9AFF: "out of unit objects (0x9aff)", 0xFEFF: "no group offers the key now (0xfeff)", 0xFDFF: "busy: every unit of the key is in use (0xfdff)",
       0xFCFF: "0xfcff", 0x9BFF: "attribute mismatch (0x9bff)", 0xCCFF: "0xccff", 0xCEFF: "0xceff"}


class Server:
    def __init__(self, stream, cfg):
        self.cfg = cfg
        self.stream, self.cur = bytes(stream), 0
        img = next(p for p in (ROOT / "work/extracted" / BUILD).rglob("cpapp-b.bin") if "nflasha8" in p.as_posix()).read_bytes()
        uc = self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        end = (BASE + len(img) + 0xFFF) & ~0xFFF
        uc.mem_map(0x100000, end - 0x100000)
        uc.mem_write(BASE, img)
        uc.mem_map(end, RAM_END - end)         # the firmware's zero-initialised data
        for a, n in ((STOP, 0x1000), (WS & ~0xFFF, 0x200000), (STK, 0x40000), (REQ, 0x3000)):
            uc.mem_map(a, n)
        self.outside, self.fatal, self.opens = {}, [], []
        uc.hook_add(UC_HOOK_CODE, self.hook)

    def hook(self, uc, addr, size, _):
        if MOD[0] <= addr < MOD[1] and addr not in FATAL and addr not in SKIP or HELP[0] <= addr < HELP[1] or addr == STOP:
            return
        lr = uc.reg_read(A.UC_ARM_REG_LR)
        if addr == GETCFG:
            dst, n = uc.reg_read(A.UC_ARM_REG_R0), uc.reg_read(A.UC_ARM_REG_R1)
            uc.mem_write(dst, self.stream[self.cur:self.cur + n].ljust(n, b"\xff"))
            self.cur += n
        elif addr in FATAL:
            self.fatal.append(hex(lr))
        else:
            k = hex(addr)
            self.outside[k] = self.outside.get(k, 0) + 1
        uc.reg_write(A.UC_ARM_REG_R0, 0)
        uc.reg_write(A.UC_ARM_REG_PC, lr)

    def call(self, addr, *args):
        uc = self.uc
        for r, v in zip((A.UC_ARM_REG_R0, A.UC_ARM_REG_R1, A.UC_ARM_REG_R2, A.UC_ARM_REG_R3), list(args) + [0] * 4):
            uc.reg_write(r, v & 0xFFFFFFFF)
        uc.reg_write(A.UC_ARM_REG_SP, STK + 0x30000)
        uc.reg_write(A.UC_ARM_REG_LR, STOP | 1)
        try:
            uc.emu_start(addr | 1, STOP, count=80_000_000)
        except UcError as e:
            raise SystemExit(f"stopped in {addr:#x}: {e} at pc {uc.reg_read(A.UC_ARM_REG_PC):#x}, lr {uc.reg_read(A.UC_ARM_REG_LR):#x}")
        return uc.reg_read(A.UC_ARM_REG_R0)

    def u32(self, a):
        return struct.unpack("<I", self.uc.mem_read(a, 4))[0]

    def init(self):
        r = self.call(INIT, 0, WS)
        return r if r < 0x8000 else r - 0x10000

    # ---- the firmware's RAM copy of the configuration
    def record_addr(self, u):
        return parse_dmmcfg.RAM[BUILD]["unit_records"] + u["seq"] * 0x14

    def units(self, key, gid):
        us = [u for u in self.cfg.units_by_key.get(key, []) if u["group"]["gid"] == gid]
        if not us:
            raise SystemExit(f"no unit record of key {key:#x} in group {gid:#x}")
        return us

    def set_size(self, key, gid, size):
        out = []
        for u in self.units(key, gid):
            a = self.record_addr(u) + 12
            out.append({"key": hex(key), "group": hex(gid), "ram_address": hex(a), "old": self.u32(a), "new": size})
            self.uc.mem_write(a, struct.pack("<I", size))
        return out

    def set_limit(self, gid, n):
        g = next(g for g in self.cfg.groups if g["gid"] == gid)
        a = parse_dmmcfg.RAM[BUILD]["group_records"] + g["index"] * 0x50 + 0x10
        old = bytes(self.uc.mem_read(a, 64))
        self.uc.mem_write(a, bytes([n]) * 64)
        return [{"group": hex(gid), "ram_address": hex(a), "old": old.hex() if len(set(old)) > 1 else old[0], "new": n}]

    def drop(self, key, gid, new_key=0x8FE):
        out = []
        for u in self.units(key, gid):
            a = self.record_addr(u) + 8
            out.append({"key": hex(key), "group": hex(gid), "ram_address": hex(a), "old": hex(self.u32(a)), "new": hex(new_key)})
            self.uc.mem_write(a, struct.pack("<I", new_key))
        return out

    def scene(self, n):
        ws = self.u32(G_UNITS)
        idx = struct.unpack("<H", self.uc.mem_read(ws + 0x11618 * 2, 2))[0]
        self.uc.mem_write(ws + 0x1161C * 2 + idx * 2, struct.pack("<H", n))

    # ---- requests
    def request(self, cmd, mode, id_or_handle):
        b = bytearray(0x100)
        struct.pack_into("<H", b, 0xC, cmd)
        struct.pack_into("<I", b, 0x10 if cmd == 0x20 else 0x14, id_or_handle)
        struct.pack_into("<HH", b, 0x20, 0x55, mode)
        self.uc.mem_write(REQ, bytes(b))
        self.uc.mem_write(REP, bytes(0x1000))

    def open(self, mem_id, mode=1):
        self.request(0x20, mode, mem_id)
        self.call(OPEN, REQ, REP, AUX)
        b = bytes(self.uc.mem_read(REP, 0x18))
        x = bytes(self.uc.mem_read(AUX, 0xC0))          # the dispatcher passes reply + 0x18 here: the extent list {u64 address, u32 size, u32}
        code = struct.unpack_from("<H", b, 0xA)[0]
        cnt = struct.unpack_from("<H", b, 8)[0]
        row = self.cfg.id_rows.get(mem_id)
        e = {"step": "open", "id": hex(mem_id), "key": hex(row["keys"][0]) if row and row["keys"] else None, "result": ERR.get(code, hex(code)), "ok": code == 0,
             "handle": hex(struct.unpack_from("<I", b, 0xC)[0]),
             "extents": [{"address": hex(struct.unpack_from("<Q", x, 16 * i)[0]), "size": struct.unpack_from("<I", x, 8 + 16 * i)[0]} for i in range(min(cnt, 12))] if code == 0 else []}
        self.opens.append(e)
        return e

    def free(self, n):
        h = int(self.opens[n]["handle"], 16)
        self.request(0x23, 2, h)
        self.call(FREE, REQ, REP)
        code = struct.unpack("<H", self.uc.mem_read(REP + 0xA, 2))[0]
        return {"step": "free", "open": n, "handle": hex(h), "result": ERR.get(code, hex(code)), "ok": code == 0}

    def objects(self):
        """Live unit objects: the 0x50-byte records of the server's pool (index, flags, base, offset, size, parent, key, owner, group)."""
        ws = self.u32(G_UNITS)
        out = []
        raw = bytes(self.uc.mem_read(ws, 0x580 * 0x50))
        by_addr = {}
        for i in range(0x580):
            o = raw[i * 0x50:(i + 1) * 0x50]
            idx, flags = struct.unpack_from("<HH", o, 0)
            base = struct.unpack_from("<Q", o, 8)[0]
            off, size = struct.unpack_from("<II", o, 0x10)
            parent, key, owner = struct.unpack_from("<III", o, 0x20)
            split_group = struct.unpack_from("<I", o, 0x30)[0]
            if size == 0 and key == 0:
                continue
            by_addr[ws + i * 0x50] = key
            out.append({"object": i, "key": key, "address": base + off, "size": size, "in_use": owner != 0, "split": bool(flags & 1),
                        "split_as_group": split_group if flags & 1 and split_group < 0x400 else None, "_parent": parent})
        res = []
        split = {ws + o["object"] * 0x50 for o in out if o["split"]}
        for o in out:
            p = o.pop("_parent")
            if p and p not in split:
                continue                          # left over from a division that was merged back
            res.append({"key": hex(o["key"]), "address": hex(o["address"]), "size": o["size"], "in_use": o["in_use"],
                        "split_as_group": None if o["split_as_group"] is None else hex(o["split_as_group"]),
                        "parent_key": hex(by_addr[p]) if p in by_addr else None})
        return res

    def snapshot(self):
        """The memory a camera read of the server's state would copy (CT6 level 12), as {name: (address, bytes)}: the page of
        pointers, the copies of the unit and group records, and the workspace (handle records, unit objects, scene, counters)."""
        rd = lambda a, n: bytes(self.uc.mem_read(a, n))
        ws = self.u32(G_WS)
        start = ws & ~0xFFF
        g, R = G_UNITS & ~0xFFF, parse_dmmcfg.RAM[BUILD]
        u, gr = R["region_records"] & ~0xFFF, R["group_records"] & ~0xFFF
        return {"globals": (g, rd(g, 0x1000)), "unit_records": (u, rd(u, 0x7000)),
                "group_records": (gr, rd(gr, 0x4000)), "workspace": (start, rd(start, ((ws + WS_LEN + 0xFFF) & ~0xFFF) - start))}

    def ram_copy_equals_file(self):
        """Compare the firmware's RAM copy (after its own parse) with the parser's reading."""
        cfg, R = self.cfg, parse_dmmcfg.RAM[BUILD]
        bad = []
        for r in cfg.regions:
            if bytes(self.uc.mem_read(R["region_records"] + r["index"] * 0x14, 0x14)) != cfg.data[r["at"]:r["at"] + 0x14]:
                bad.append(f"region {r['key']:#x}")
        for g in cfg.groups:
            got = bytes(self.uc.mem_read(R["group_records"] + g["index"] * 0x50 + 4, 0x4C))
            if got != cfg.data[g["at"] + 4:g["at"] + 0x50]:
                bad.append(f"group {g['gid']:#x}")
            for u in g["units"]:
                if bytes(self.uc.mem_read(self.record_addr(u), 0x14)) != cfg.data[u["at"]:u["at"] + 0x14]:
                    bad.append(f"unit {u['key']:#x} of group {g['gid']:#x}")
        ids = bytes(self.uc.mem_read(R["id_rows"], 8 * len(cfg.ids)))
        for n, row in enumerate(cfg.ids):
            i, ptr = struct.unpack_from("<II", ids, n * 8)
            keys = []
            while True:
                k = self.u32(ptr + 4 * len(keys))
                if k == 0xFFFFFFFF or len(keys) > 8:
                    break
                keys.append(k)
            if i != row["id"] or keys != row["keys"]:
                bad.append(f"id row {n}: {i:#x} {keys}")
        return bad


def triples(text, n=3):
    out = []
    for item in filter(None, text.split(",")):
        parts = [int(x, 0) for x in item.split(":")]
        if len(parts) != n:
            raise SystemExit(f"bad item {item!r}")
        out.append(parts)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan", nargs="?", default="")
    ap.add_argument("--size", default="")
    ap.add_argument("--size-in", default="ram", choices=["ram", "stream"])
    ap.add_argument("--limit", default="")
    ap.add_argument("--drop", default="")
    ap.add_argument("--scene", type=int)
    ap.add_argument("--out", default="")
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument("--build", default="a7iv_602")
    a = ap.parse_args()
    use_build(a.build)
    cfg = parse_dmmcfg.Config(parse_dmmcfg.find_file(BUILD), BUILD)
    stream = bytearray(cfg.data)
    changes = []
    if a.size_in == "stream":
        for key, gid, size in triples(a.size):
            for u in [u for u in cfg.units_by_key.get(key, []) if u["group"]["gid"] == gid]:
                struct.pack_into("<I", stream, u["at"] + 12, size)
                changes.append({"where": "stream before set-up", "key": hex(key), "group": hex(gid), "file_offset": hex(u["at"] + 12), "old": u["size"], "new": size})
    s = Server(stream, cfg)
    rc = s.init()
    res = {"about": "The coprocessor's DMM server code run alone on the configuration stream. Generated by build/emu_dmm_server.py; see its header for what is the "
                    "firmware's own and what is made up.",
           "set_up_result": rc, "stream_bytes_read": s.cur, "stream_size": len(stream), "fatal_reports": list(s.fatal), "changes": changes, "steps": []}
    if a.selfcheck:
        bad = s.ram_copy_equals_file()
        ok = rc == 0 and s.cur == len(stream) and not s.fatal and not bad
        print("set-up result", rc, "| stream read", s.cur, "of", len(stream), "| fatal reports", s.fatal, "| RAM copy differs in", len(bad), bad[:5])
        e, e2 = s.open(0x4AF), s.open(0x4AF)
        print("open 0x4af twice:", e["result"], e["extents"], e2["result"], e2["extents"])
        ok &= e["ok"] and e2["ok"] and [x["size"] for x in e["extents"] + e2["extents"]] == [2471040, 2471040] and e["extents"] != e2["extents"]
        print("outside calls:", s.outside)
        print("selfcheck", "passed" if ok else "FAILED")
        raise SystemExit(0 if ok else 1)
    if a.size_in == "ram":
        for key, gid, size in triples(a.size):
            changes += [dict(c, where="RAM copy after set-up") for c in s.set_size(key, gid, size)]
    for gid, n in triples(a.limit, 2):
        changes += [dict(c, where="RAM copy after set-up", what="per-scene limit bytes") for c in s.set_limit(gid, n)]
    for key, gid in triples(a.drop, 2):
        changes += [dict(c, where="RAM copy after set-up", what="unit key replaced") for c in s.drop(key, gid)]
    if a.scene is not None:
        s.scene(a.scene)
        res["scene"] = a.scene
    for step in filter(None, a.plan.split(",")):
        p = step.split(":")
        if p[0] == "open":
            res["steps"].append(s.open(int(p[1], 0)))
        elif p[0] == "free":
            res["steps"].append(s.free(int(p[1], 0)))
        elif p[0] == "dump":
            res["steps"].append({"step": "dump", "objects": s.objects()})
        elif p[0] == "size":
            res["steps"].append({"step": "size", "changes": s.set_size(int(p[1], 0), int(p[2], 0), int(p[3], 0))})
        elif p[0] == "limit":
            res["steps"].append({"step": "limit", "changes": s.set_limit(int(p[1], 0), int(p[2], 0))})
        elif p[0] == "drop":
            res["steps"].append({"step": "drop", "changes": s.drop(int(p[1], 0), int(p[2], 0))})
        else:
            raise SystemExit(f"unknown step {step!r}")
    res["fatal_reports"] = list(s.fatal)
    res["outside_calls"] = s.outside
    live = [e["extents"] for e in s.opens if e["ok"]]
    spans = sorted((int(x["address"], 16), int(x["address"], 16) + x["size"]) for ext in live for x in ext)
    res["final_objects"] = s.objects()
    for st in res["steps"]:
        if st["step"] == "open":
            print(f"open {st['id']} (key {st['key']}): {st['result']}  " + "  ".join(f"{x['address']} +{x['size']:,}" for x in st["extents"]))
        elif st["step"] == "free":
            print(f"free open#{st['open']}: {st['result']}")
        elif st["step"] == "dump":
            for o in st["objects"]:
                print(f"    object key {o['key']:>6s} at {o['address']} size {o['size']:>11,} {'IN USE' if o['in_use'] else 'free  '} parent {o['parent_key']} split as {o['split_as_group']}")
        else:
            print(st["step"], st["changes"])
    print("fatal reports:", res["fatal_reports"], "| outside calls:", res["outside_calls"])
    if a.out:
        (ROOT / f"evidence/hardware/dmm_server_{a.out}.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf8", newline="\n")
        print(f"wrote evidence/hardware/dmm_server_{a.out}.json")


if __name__ == "__main__":
    main()
