"""Decode a DMM configuration stream (DmmCfg.bin) in the order the coprocessor firmware reads it.

The format is the reader's own (cpapp-b.bin of a7iv_602: 0xaffbba calls 0xafdac6 -> 0xaff040, then 0xb00c86, then 0xafc582),
read sequentially with dmm_module_GetConfigData 0x505338:

  section A   0x50-byte head record, then 0x14-byte region records {base low, u16, u16 base high, key, size, attributes}
              up to a record whose key is 0xffffffff; the section ends with a head record whose +8 is 0xffffffff
  section B   0x50-byte group records {0, u16, u16, parent key, group id, 64 per-scene limit bytes}, each followed by
              0x14-byte unit records {0, type, key, size, attributes} up to key 0xffffffff; ends with a group record whose
              +8 is 0xffffffff. A group is one way of dividing its parent (a region or a unit); several groups with the
              same parent are alternatives. The type is log2 of the unit's alignment (0xafef78, 0xafddfa).
  id table    rows {memory id, 0, key, key, ..., 0xffffffff}; ends with an id of 0xffffffff (8 bytes)
  stamp       0x2c bytes of text

The memory id is what code passes to the unit open (DmmWrapper::AllocNew 0x478368, 0x479c5c, 0x479dd8).
Until 2026-11-18 this script paired each id with the key of the row before it (findings F506 and F668 rest on that
mistake; see their successors) and dropped the units in on-chip memory (attributes 0x10000).

  python build/parse_dmmcfg.py [id ...]         the ids' units -> evidence/hardware/dmm_units.json  (default ids: 0x4af 0x80170417)
      --build B        another build (default a7iv_602)
      --file nflasha8|setting                   the coprocessor's stream (default) or the file dmm.ko gets
      --full           also write evidence/hardware/dmm_config_<build>.json (everything decoded)
      --page           also write reference/dmm_config_<build>.md
      --xbuild ID...   print the units of these ids in every build on disk, write nothing
      --selfcheck      check the decode of a7iv_602 against known facts, write nothing
"""
import argparse
import collections
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACTED = ROOT / "work/extracted"
END = 0xFFFFFFFF
# where the firmware keeps its copies (cpapp-b.bin addresses, from 0xaff040 and 0xb00c86); known for this build only
RAM = {"a7iv_602": {"region_records": 0x1F730BC, "unit_records": 0x1F735BC, "group_records": 0x1D9B618, "head_records": 0x1D9B578,
                    "id_rows": 0x1FAE380, "id_keys": 0x1FB0380},
       # A7C II 2.01 (2026-11-24): the same reader moved as one block (0xaff040 -> 0xc1d79a, 0xb00c86 -> 0xc1f3e0, +0x11e75a);
       # the addresses are the MOVW/MOVT values diff_consts.py lines up there
       "a7c2_201": {"region_records": 0x257CC24, "unit_records": 0x257D124, "group_records": 0x23A5180, "head_records": 0x23A50E0,
                    "id_rows": 0x25B7EE8, "id_keys": 0x25B9EE8},
       # ZV-E1 2.02 (2026-11-24): the A7C II's readers at -0x1f738 (0xbfe062, 0xbffca8); every copy 0x20a8 below the A7C II's (diff_consts.py)
       "zve1_202": {"region_records": 0x257AB7C, "unit_records": 0x257B07C, "group_records": 0x23A30D8, "head_records": 0x23A3038,
                    "id_rows": 0x25B5E40, "id_keys": 0x25B7E40},
       # FX2 1.01 (2026-11-25): the A7C II's readers 0xc1d79a / 0xc1f3e0 are 0xcb9f96 / 0xcbbe5c (match_thumb); the MOVW/MOVT values
       # diff_consts.py lines up there (every copy 0xfea48 below the A7C II's)
       "fx2_101": {"region_records": 0x247E1DC, "unit_records": 0x247E6DC, "group_records": 0x22A6738, "head_records": 0x22A6698,
                   "id_rows": 0x24B94A0, "id_keys": 0x24BB4A0},
       # FX30 6.01 (2026-11-26, FX30 port): the A7 IV's readers 0xaff040 / 0xb00c86 are 0xb6796e / 0xb695b4 (match_thumb, one hit each, the
       # whole module +0x6892e); the MOVW/MOVT values diff_consts.py lines up there: every copy 0x108180 above the A7 IV's
       "fx30_601": {"region_records": 0x207B23C, "unit_records": 0x207B73C, "group_records": 0x1EA3798, "head_records": 0x1EA36F8,
                    "id_rows": 0x20B6500, "id_keys": 0x20B8500},
       # A1 II 4.00 (2026-11-26, A1 II port): the FX2's readers 0xcb9f96 / 0xcbbe5c are 0xcb60ae / 0xcb7ec8 (match_thumb, one hit each); the
       # MOVW/MOVT values diff_consts.py lines up there: every copy 0x1bf0 below the FX2's
       "a1m2_400": {"region_records": 0x247C5EC, "unit_records": 0x247CAEC, "group_records": 0x22A4B48, "head_records": 0x22A4AA8,
                    "id_rows": 0x24B78B0, "id_keys": 0x24B98B0},
       # FX6 6.02 (2026-11-26, after the testers' first runs, repo issue 2): the A7 IV's readers 0xaff040 / 0xb00c86 are 0xac61a4 / 0xac7f7c
       # (match_thumb, one hit each); the MOVW/MOVT values diff_consts.py lines up there. Checked against a tester's dump of the camera's
       # own copy: all 1,058 unit records at these addresses equal the file (build_dmm_fx6.py)
       "fx6_602": {"region_records": 0x213EA64, "unit_records": 0x213EF64, "group_records": 0x1F991C0, "head_records": 0x1F99120,
                   "id_rows": 0x2179D28, "id_keys": 0x217BD28},
       # A6700 2.00 (2026-11-26, A6700 port): the ZV-E1's readers 0xbfe062 / 0xbffca8 (= A7C II 0xc1d79a / 0xc1f3e0, FX30 0xb6796e /
       # 0xb695b4) are 0xc00fa8 / 0xc02bee (match_thumb, one hit each from all three); the MOVW/MOVT values diff_consts.py lines up there:
       # every copy 0xc28 above the ZV-E1's
       "a6700_200": {"region_records": 0x257B7A4, "unit_records": 0x257BCA4, "group_records": 0x23A3D00, "head_records": 0x23A3C60,
                     "id_rows": 0x25B6A68, "id_keys": 0x25B8A68}}


def find_file(build, which="nflasha8"):
    hits = [p for p in (EXTRACTED / build).rglob("DmmCfg.bin") if ("/" + which + "/") in p.as_posix()]
    if not hits:
        raise SystemExit(f"no {which} DmmCfg.bin under work/extracted/{build}")
    return hits[0]


def decode(d):
    """Walk the stream as the firmware does. Raises ValueError where the firmware would call its fatal report."""
    u32 = lambda o: struct.unpack_from("<I", d, o)[0]
    u16 = lambda o: struct.unpack_from("<H", d, o)[0]
    o = 0
    heads, regions = [], []
    while True:                                                   # section A (0xaff040, first loop)
        if len(heads) + 1 > 2:
            raise ValueError("more than one head record")
        head = {"at": o, "u16_4": u16(o + 4), "u16_6": u16(o + 6), "key": u32(o + 8), "word_c": u32(o + 12), "bytes": d[o + 16:o + 0x50].hex()}
        o += 0x50
        if head["key"] == END:
            break
        heads.append(head)
        while True:
            if len(regions) + 1 > 0x40:
                raise ValueError("more than 0x40 region records")
            key = u32(o + 8)
            if key == END:
                o += 0x14
                break
            if key > 0x8FF:
                raise ValueError(f"region key {key:#x} at {o:#x}")
            regions.append({"at": o, "index": len(regions), "key": key, "base": u32(o) | (u16(o + 6) << 32), "u16_4": u16(o + 4), "size": u32(o + 12), "attr": u32(o + 16)})
            o += 0x14
    groups, n14 = [], 0                                           # section B (0xaff040, second loop); n14 counts 0x14-byte records
    while True:
        if len(groups) + 1 > 0x400:
            raise ValueError("more than 0x400 group records")
        g = {"at": o, "index": len(groups), "u16_4": u16(o + 4), "u16_6": u16(o + 6), "parent": u32(o + 8), "gid": u32(o + 12), "limits": d[o + 16:o + 0x50], "units": []}
        o += 0x50
        if g["parent"] == END:
            break
        if g["gid"] > 0x400:
            raise ValueError(f"group id {g['gid']:#x} at {g['at']:#x}")
        while True:
            key = u32(o + 8)
            if key == END:
                o += 0x14
                n14 += 1
                break
            if key > 0x8FF:
                raise ValueError(f"unit key {key:#x} at {o:#x}")
            if len(g["units"]) + 1 > 0x260:
                raise ValueError("more than 0x260 units in a group")
            g["units"].append({"at": o, "seq": n14, "word_0": u32(o), "type": u32(o + 4), "key": key, "size": u32(o + 12), "attr": u32(o + 16), "group": g})
            o += 0x14
            n14 += 1
        groups.append(g)
    ids = []                                                      # id table (0xb00c86)
    while True:
        if len(ids) + 1 > 0x400:
            raise ValueError("more than 0x400 id rows")
        row = {"at": o, "id": u32(o), "word_4": u32(o + 4), "keys": []}
        o += 8
        if row["id"] == END:
            break
        while True:
            k = u32(o)
            o += 4
            if k == END:
                break
            row["keys"].append(k)
        ids.append(row)
    stamp = d[o:o + 0x2C]                                         # 0xafc582
    o += 0x2C
    return {"heads": heads, "regions": regions, "groups": groups, "ids": ids, "stamp": stamp, "consumed": o, "size": len(d)}


class Config:
    def __init__(self, path, build=None):
        self.file, self.build = Path(path), build
        self.data = self.file.read_bytes()
        self.__dict__.update(decode(self.data))
        self.region_by_key = {r["key"]: r for r in self.regions}
        self.units_by_key = collections.defaultdict(list)
        for g in self.groups:
            for u in g["units"]:
                self.units_by_key[u["key"]].append(u)
        self.ids_by_key = collections.defaultdict(list)
        for row in self.ids:
            for k in row["keys"]:
                self.ids_by_key[k].append(row["id"])
        self.id_rows = {row["id"]: row for row in self.ids}
        self._bases = {}

    def exact(self):
        return self.consumed == self.size

    @staticmethod
    def align(unit_type):
        return 0 if (unit_type & 0xFFFF) >= 0x20 else 1 << (unit_type & 0xFF)

    def layout(self, group, base):
        """Offsets of a group's units and the layout's total for a parent that starts at 'base' (0xafef78, 0xafddfa)."""
        low, run, offs = base & 0xFFFFFFFF, 0, []
        for u in group["units"]:
            a = self.align(u["type"])
            off = (((run + low - 1 + a) & -a) - low) & 0xFFFFFFFF
            offs.append(off)
            run = off + u["size"]
        return offs, run

    def bases(self, key, _seen=()):
        """Every absolute address a region or unit with this key can start at, over all alternative layouts."""
        if key in self._bases:
            return self._bases[key]
        if key in self.region_by_key:
            out = {self.region_by_key[key]["base"]}
        elif key in _seen:
            out = set()
        else:
            out = set()
            for u in self.units_by_key.get(key, []):
                g = u["group"]
                for pb in self.bases(g["parent"], _seen + (key,)):
                    offs, _ = self.layout(g, pb)
                    out.add(pb + offs[g["units"].index(u)])
        if not _seen:
            self._bases[key] = out
        return out

    def parent_sizes(self, key):
        if key in self.region_by_key:
            return {self.region_by_key[key]["size"]}
        return {u["size"] for u in self.units_by_key.get(key, [])}

    def group_fit(self, g):
        """(largest layout total over the parent's possible bases, smallest parent size); None if the parent is unknown."""
        sizes, bases = self.parent_sizes(g["parent"]), self.bases(g["parent"])
        if not sizes or not bases:
            return None
        return max(self.layout(g, b)[1] for b in bases), min(sizes)

    def path(self, key, _seen=()):
        if key in self.region_by_key:
            return f"{key:x}"
        if key in _seen or key not in self.units_by_key:
            return f"?{key:x}"
        parents = sorted({u["group"]["parent"] for u in self.units_by_key[key]})
        tail = [self.path(p, _seen + (key,)) for p in parents]
        return f"{key:x}/" + (tail[0] if len(tail) == 1 else "{" + "|".join(tail) + "}")

    def ram(self, what, n=0):
        base = RAM.get(self.build, {}).get(what) if "/nflasha8/" in self.file.as_posix() else None
        return None if base is None else base + n

    def unit_json(self, u):
        r = {"record_at": hex(u["at"]), "size_field_at": hex(u["at"] + 12), "group": hex(u["group"]["gid"]), "parent_key": hex(u["group"]["parent"]),
             "type": u["type"], "alignment": self.align(u["type"]), "size_bytes": u["size"], "size_hex": hex(u["size"]), "attributes": hex(u["attr"])}
        addr = self.ram("unit_records", u["seq"] * 0x14)
        if addr is not None:
            r["ram_record_at"], r["ram_size_field_at"] = hex(addr), hex(addr + 12)
        return r

    def id_json(self, i):
        row = self.id_rows.get(i)
        if row is None:
            return {"id": hex(i), "found": False}
        return {"id": hex(i), "found": True, "id_row_at": hex(row["at"]),
                "keys": [{"key": hex(k), "path_to_region": self.path(k), "units": [self.unit_json(u) for u in self.units_by_key.get(k, [])]} for k in row["keys"]]}

    def summary(self):
        return {"file": self.file.relative_to(ROOT).as_posix(), "file_size": self.size, "consumed": self.consumed, "consumed_exactly": self.exact(),
                "regions": len(self.regions), "groups": len(self.groups), "unit_records": sum(len(g["units"]) for g in self.groups),
                "keys": len(self.units_by_key), "ids": len(self.ids),
                "ids_without_unit_records": sum(1 for r in self.ids if not any(k in self.units_by_key or k in self.region_by_key for k in r["keys"])),
                "stamp": self.stamp.decode("latin1").rstrip("\x00 ")}

    def limits_text(self, g):
        vals = sorted(set(g["limits"]))
        return str(vals[0]) if len(vals) == 1 else g["limits"].hex()

    def full_json(self):
        out = {"about": "Everything build/parse_dmmcfg.py decodes from this DMM configuration stream, in the firmware's reading order. "
                        "A group is one way of dividing its parent; groups with the same parent are alternatives. 'limits' is the group's 64 per-scene "
                        "bytes (one number when they are all equal): how many times the layout may be in use at once in that scene (0xafddfa). "
                        "RAM addresses are cpapp-b.bin addresses of the firmware's copy, given for a7iv_602's coprocessor stream only.",
               "format": "firmware order (cpapp-b.bin 0xaff040, 0xb00c86, 0xafc582)"}
        out.update(self.summary())
        out["heads"] = [{k: (hex(v) if isinstance(v, int) else v) for k, v in h.items()} for h in self.heads]
        out["regions"] = [{"record_at": hex(r["at"]), "key": hex(r["key"]), "base": hex(r["base"]), "size_bytes": r["size"], "size_hex": hex(r["size"]),
                           "attributes": hex(r["attr"]), "u16_4": r["u16_4"]} for r in self.regions]
        gl = []
        for g in self.groups:
            fit = self.group_fit(g)
            e = {"record_at": hex(g["at"]), "group": hex(g["gid"]), "parent_key": hex(g["parent"]), "u16_4": g["u16_4"], "u16_6": g["u16_6"], "limits": self.limits_text(g),
                 "layout_total": None if fit is None else fit[0], "parent_size": None if fit is None else fit[1], "fits": None if fit is None else fit[0] <= fit[1],
                 "units": [{"key": hex(u["key"]), "ids": [hex(i) for i in self.ids_by_key.get(u["key"], [])], **self.unit_json(u)} for u in g["units"]]}
            addr = self.ram("group_records", g["index"] * 0x50)
            if addr is not None:
                e["ram_record_at"] = hex(addr)
            gl.append(e)
        out["groups"] = gl
        out["ids"] = [{"id": hex(r["id"]), "id_row_at": hex(r["at"]), "keys": [hex(k) for k in r["keys"]]} for r in self.ids]
        return out


def mib(n):
    return f"{n / 1048576:.1f}"


def page(cfg):
    s = cfg.summary()
    L = [f"# DMM configuration of `{cfg.build}` ({'coprocessor' if '/nflasha8/' in s['file'] else 'Linux side'} stream), decoded", "",
         f"Generated by `build/parse_dmmcfg.py --build {cfg.build} --page`; do not edit by hand. The format and the allocator that uses it are in "
         "[dmm_memory_manager.md](dmm_memory_manager.md). The same data, with the file offset of every record, is in "
         f"`evidence/hardware/dmm_config_{cfg.build}.json`.", "",
         f"**File:** `{s['file']}`, {s['file_size']:,} bytes, consumed {'exactly' if s['consumed_exactly'] else 'NOT exactly'}. "
         f"{s['regions']} regions, {s['groups']} groups, {s['unit_records']:,} unit records with {s['keys']} keys, {s['ids']} memory ids. Stamp: `{s['stamp']}`.", "",
         "## Regions (fixed at start-up)", "", "| Key | Physical address | Size (bytes) | MiB | Attributes |", "|---|---|---|---|---|"]
    for r in cfg.regions:
        L.append(f"| `{r['key']:#x}` | `{r['base']:#x}` | {r['size']:,} | {mib(r['size'])} | `{r['attr']:#x}` |")
    L += ["", "## Memory ids", "", "The id is what code passes to the unit open. Units of one key can appear in several groups (alternative layouts); "
          "\"Records\" counts them all.", "", "| Id | Key | Records | Unit size (bytes) | Alignment | Attributes | Groups | Path to region |", "|---|---|---|---|---|---|---|---|"]
    for row in sorted(cfg.ids, key=lambda r: r["id"]):
        for k in row["keys"]:
            us = cfg.units_by_key.get(k, [])
            sizes = ", ".join(f"{x:,}" for x in sorted({u["size"] for u in us})) or "none"
            al = ", ".join(str(a) for a in sorted({cfg.align(u["type"]) for u in us}))
            at = ", ".join(f"`{a:#x}`" for a in sorted({u["attr"] for u in us}))
            gs = ", ".join(f"`{g:#x}`" for g in sorted({u["group"]["gid"] for u in us}))
            L.append(f"| `{row['id']:#x}` | `{k:#x}` | {len(us)} | {sizes} | {al} | {at} | {gs} | `{cfg.path(k)}` |")
    L += ["", "## Groups (layouts)", "", "\"Limit\" is the per-scene byte (one value when all 64 are equal). \"Free\" is the parent's size less the layout total.", "",
          "| Group | Parent key | Limit | Units (key × count: size) | Layout total | Parent size | Free |", "|---|---|---|---|---|---|---|"]
    for g in cfg.groups:
        cnt = collections.Counter((u["key"], u["size"]) for u in g["units"])
        units = "; ".join(f"`{k:#x}` × {n}: {sz:,}" for (k, sz), n in cnt.items())
        fit = cfg.group_fit(g)
        tot, ps, free = ("?", "?", "?") if fit is None else (f"{fit[0]:,}", f"{fit[1]:,}", f"{fit[1] - fit[0]:,}")
        lim = cfg.limits_text(g)
        L.append(f"| `{g['gid']:#x}` | `{g['parent']:#x}` | {lim if len(lim) < 8 else 'varies'} | {units} | {tot} | {ps} | {free} |")
    return "\n".join(L) + "\n"


def selfcheck():
    cfg = Config(find_file("a7iv_602"), "a7iv_602")
    s = cfg.summary()
    checks = [("consumed to the exact byte", cfg.exact() and s["file_size"] == 42976),
              ("11 regions, 169 groups, 1006 unit records, 339 ids", (s["regions"], s["groups"], s["unit_records"], s["ids"]) == (11, 169, 1006, 339)),
              ("stamp names the coprocessor build", s["stamp"].startswith("for ilc8g8g32m-ipsxcp"))]

    def one(i):
        row = cfg.id_rows.get(i)
        return None if row is None or len(row["keys"]) != 1 else (row["keys"][0], sorted(u["size"] for u in cfg.units_by_key[row["keys"][0]]))

    for n in range(4):
        checks.append((f"id {0x441 + n:#x} is one 364,800-byte unit of key {0x582 + n:#x} in on-chip memory",
                       one(0x441 + n) == (0x582 + n, [364800]) and all(u["attr"] == 0x10000 for u in cfg.units_by_key[0x582 + n])))
        checks.append((f"id {0x4a0 + n:#x} is one 364,800-byte unit of key {0x618 + n:#x}", one(0x4A0 + n) == (0x618 + n, [364800])))
    checks += [("id 0x4af is key 0x62a, two units of 2,471,040 bytes", one(0x4AF) == (0x62A, [2471040] * 2)),
               ("id 0x43e is key 0x57f, four records of 27,864,320 bytes", one(0x43E) == (0x57F, [27864320] * 4)),
               ("id 0x608 is key 0x6a3, eighteen records of 27,864,320 bytes", one(0x608) == (0x6A3, [27864320] * 18)),
               ("27,864,320 = 7040 x 1979 x 2 and no other key has a size divisible by 1979",
                27864320 == 7040 * 1979 * 2 and {k for k, us in cfg.units_by_key.items() if any(u["size"] % 1979 == 0 for u in us)} == {0x57F, 0x6A3}),
               ("every group's layout fits its parent", all((f := cfg.group_fit(g)) is not None and f[0] <= f[1] for g in cfg.groups)),
               ("every id has exactly one key; 52 ids name a key this product gives no unit records",
                all(len(r["keys"]) == 1 for r in cfg.ids) and s["ids_without_unit_records"] == 52),
               ("regions are contiguous within each bank", all(a["base"] + a["size"] == b["base"] for a, b in zip(cfg.regions, cfg.regions[1:]) if a["base"] >> 32 == b["base"] >> 32 == 8)),
               ("firmware copy of key 0x57f's first size field is at 0x1f786a4", cfg.ram("unit_records", cfg.units_by_key[0x57F][0]["seq"] * 0x14) + 12 == 0x1F786A4)]
    others = sorted(EXTRACTED.glob("*/**/DmmCfg.bin"))
    bad = [p.relative_to(EXTRACTED).as_posix() for p in others if not Config(p).exact()]
    checks.append((f"all {len(others)} DmmCfg.bin files on disk are consumed exactly", not bad))
    ok = True
    for name, good in checks:
        print(("ok    " if good else "FAIL  ") + name)
        ok &= bool(good)
    if bad:
        print("not exact:", bad)
    print("selfcheck", "passed" if ok else "FAILED", f"({len(checks)} checks)")
    return 0 if ok else 1


def xbuild(want):
    for bdir in sorted(p for p in EXTRACTED.iterdir() if p.is_dir()):
        for which in ("nflasha8", "setting"):
            hits = [p for p in bdir.rglob("DmmCfg.bin") if ("/" + which + "/") in p.as_posix()]
            if not hits:
                continue
            cfg = Config(hits[0], bdir.name)
            total = sum(r["size"] for r in cfg.regions)
            print(f"{bdir.name:11s} {which:8s} exact={cfg.exact()} regions {len(cfg.regions):2d} total {mib(total):>8s} MiB  stamp {cfg.summary()['stamp']}")
            for i in want:
                row = cfg.id_rows.get(i)
                if row is None:
                    print(f"    id {i:#x}: absent")
                    continue
                for k in row["keys"]:
                    cnt = collections.Counter(u["size"] for u in cfg.units_by_key.get(k, []))
                    print(f"    id {i:#x} key {k:#x}: " + ", ".join(f"{n} x {sz:,}" for sz, n in sorted(cnt.items())) + f"   path {cfg.path(k)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("ids", nargs="*", help="memory ids (default 0x4af 0x80170417)")
    ap.add_argument("--build", default="a7iv_602")
    ap.add_argument("--file", default="nflasha8", choices=["nflasha8", "setting"])
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--page", action="store_true")
    ap.add_argument("--xbuild", action="store_true")
    ap.add_argument("--selfcheck", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf8")
    if a.selfcheck:
        raise SystemExit(selfcheck())
    want = [int(x, 0) for x in a.ids] or [0x4AF, 0x80170417]
    if a.xbuild:
        return xbuild(want)
    cfg = Config(find_file(a.build, a.file), a.build)
    if not cfg.exact():
        raise SystemExit(f"stream not consumed exactly: {cfg.consumed} of {cfg.size}")
    out = {"about": "Units of the requested memory ids in the DMM configuration stream. Generated by build/parse_dmmcfg.py, which reads the stream in the "
                    "firmware's own order; the full decode is evidence/hardware/dmm_config_<build>.json.",
           "format": "firmware order (cpapp-b.bin 0xaff040, 0xb00c86, 0xafc582); before 2026-11-18 this file paired each id with the previous row's key"}
    out.update(cfg.summary())
    out["requested"] = [cfg.id_json(i) for i in want]
    suffix = "" if (a.build, a.file) == ("a7iv_602", "nflasha8") else f"_{a.build}" + ("" if a.file == "nflasha8" else "_setting")
    (ROOT / f"evidence/hardware/dmm_units{suffix}.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf8", newline="\n")
    print(json.dumps(out, indent=1))
    tag = a.build + ("" if a.file == "nflasha8" else "_setting")
    if a.full:
        (ROOT / f"evidence/hardware/dmm_config_{tag}.json").write_text(json.dumps(cfg.full_json(), indent=1) + "\n", encoding="utf8", newline="\n")
        print(f"wrote evidence/hardware/dmm_config_{tag}.json", file=sys.stderr)
    if a.page:
        (ROOT / f"reference/dmm_config_{tag}.md").write_text(page(cfg), encoding="utf8", newline="\n")
        print(f"wrote reference/dmm_config_{tag}.md", file=sys.stderr)


if __name__ == "__main__":
    main()
