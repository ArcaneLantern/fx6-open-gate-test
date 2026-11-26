"""FX6 6.02: the output-plane memory designs (2026-11-26, after the testers' first runs).

  C:\\Python313\\python.exe -B build\\build_dmm_fx6.py

Why. The FX6's movie output planes (memory id 0x2d9, DmmCfg key 0x3f1) are 13,271,040 bytes and the FX6 fills them at 1.5 bytes per
pixel, so a plane holds 3840 x 2304. A 3840 x 2560 picture needs 14,745,600. With the kit's output-size step alone, clips were not
written (repo issue 1) or the last 256 rows repeated the top of the picture (repo issue 2). The A7S III, FX3 and A7 IV have the same
units and record 3840 x 2560 in them (1.25 bytes per pixel there), which is why the kit this port came from has no such step.

dmm7slot_fx6_v1   THE TESTER'S DESIGN (github.com/ArcaneLantern/fx6-open-gate-test issue 2, user Mininoob): ten words of the camera's
                  run-time copy of /cp/DmmCfg.bin. Seven of the 4K layout's eight planes get 14,745,600 bytes, the eighth leaves the
                  pool (key 0x3f1 -> 0x7fd, 4096 bytes) so that the layout still fits its 106,954,752-byte parent; and the one 4K plane
                  of the HD layout (0x26) gets 14,745,600 too, which puts that layout 688,128 bytes over the parent. RAN ON AN FX6:
                  a clean 3840 x 2560 XAVC-I clip. Here the words are derived from the firmware's file, not typed in.
dmm7slot_fx6_v2   A VARIANT, NOT RUN: the same 4K-layout words, but the HD layout's plane is retagged (key 0x3f1 -> 0x7fd) instead of
                  enlarged. In the FX6's own allocator (below) v1's enlarged HD layout answers the first request after a full release
                  with a refusal; v2 has no refusal and no layout over its parent.
dmm7slot_fx6_back PUT BACK ONLY: the eleven words of v1 and v2 together, so that one put-back library restores either.

Not shipped: the 4K-layout words alone (nine words). The allocator then hands out the HD layout's 13,271,040-byte plane first, among
the big ones: one picture in every cycle would overrun its plane.

Checks: the words against the two dumps the tester attached (evidence/fx6/issue2), the fit of every layout, and the FX6's own allocator
(emu_dmm_server.py, fx6_602) on the stock and the changed tables. Writes modding/designs/<name>.json and evidence/fx6/dmm7slot_fx6_emu.json.
Design only: nothing is sent to a camera.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import emu_dmm_server as E  # noqa: E402
import parse_dmmcfg as P  # noqa: E402

BUILD = "fx6_602"
KEY, HD_GROUP, UHD_GROUP, PARENT = 0x3F1, 0x26, 0x28, 0x39
PARENT_SIZE = 106_954_752
OLD, NEW = 13_271_040, 14_745_600                       # 4096 x 2160 x 1.5 and 3840 x 2560 x 1.5
SPARE_KEY, SPARE_SIZE = 0x7FD, 4096
KEY_LIMIT = 0x800                                      # the FX6 reader's fatal test (0xac623e cmp r0, #0x800; the A7 IV's is 0x900)
MEM_ID = 0x2D9
# the ten addresses of the tester's report, to compare with
ISSUE2 = [0x2141CAC, 0x2141D10, 0x2141D24, 0x2141D38, 0x2141D4C, 0x2141D60, 0x2141D74, 0x2141D88, 0x2141D98, 0x2141D9C]
DUMPS = ROOT / "evidence/fx6/issue2"
DUMP_BASE = 0x213E000
NAMES = ("dmm7slot_fx6_v1", "dmm7slot_fx6_v2")
w32 = lambda v: struct.pack("<I", v)


def ram_table(cfg):
    """The firmware's run-time copy of the unit records, rebuilt from the file: (base address, bytes, {seq: file offset}).
    The copy holds every 0x14-byte record of section B in file order, end markers included; the 0x50-byte group records are elsewhere."""
    recs, at, seq = [], {}, 0
    for g in cfg.groups:
        o = g["at"] + 0x50
        for u in g["units"]:
            assert u["seq"] == seq and u["at"] == o
            recs.append(cfg.data[o:o + 0x14])
            at[seq] = o
            o, seq = o + 0x14, seq + 1
        assert cfg.data[o + 8:o + 12] == b"\xff" * 4               # the group's end marker
        recs.append(cfg.data[o:o + 0x14])
        at[seq] = o
        seq += 1
    return P.RAM[BUILD]["unit_records"], b"".join(recs), at


def designs(cfg):
    R = P.RAM[BUILD]["unit_records"]
    ra = lambda u: R + u["seq"] * 0x14
    g_hd = next(g for g in cfg.groups if g["gid"] == HD_GROUP)
    g_4k = next(g for g in cfg.groups if g["gid"] == UHD_GROUP)
    assert g_hd["parent"] == g_4k["parent"] == PARENT and cfg.parent_sizes(PARENT) == {PARENT_SIZE}
    hd = [u for u in g_hd["units"] if u["key"] == KEY]
    assert len(hd) == 1 and hd[0] is g_hd["units"][-1] and len(g_hd["units"]) == 29
    assert [u["key"] for u in g_4k["units"]] == [KEY] * 8 and {u["size"] for u in g_4k["units"]} | {hd[0]["size"]} == {OLD}
    assert sorted(u["seq"] for u in cfg.units_by_key[KEY]) == sorted([hd[0]["seq"]] + [u["seq"] for u in g_4k["units"]])
    hd, last = hd[0], g_4k["units"][7]
    common = [(ra(u) + 12, w32(OLD), w32(NEW), u, "4K layout 0x28, plane %d of 8: size 13,271,040 -> 14,745,600" % (k + 1)) for k, u in enumerate(g_4k["units"][:7])]
    common += [(ra(last) + 8, w32(KEY), w32(SPARE_KEY), last, "4K layout 0x28, plane 8: key 0x3f1 -> 0x7fd (it leaves the pool)"),
               (ra(last) + 12, w32(OLD), w32(SPARE_SIZE), last, "4K layout 0x28, plane 8: size 13,271,040 -> 4,096")]
    v1 = [(ra(hd) + 12, w32(OLD), w32(NEW), hd, "HD layout 0x26, its one 4K plane: size 13,271,040 -> 14,745,600 (the layout is then 688,128 bytes over its parent)")] + common
    v2 = [(ra(hd) + 8, w32(KEY), w32(SPARE_KEY), hd, "HD layout 0x26, its one 4K plane: key 0x3f1 -> 0x7fd (the layout no longer offers an output plane)")] + common
    return {"dmm7slot_fx6_v1": v1, "dmm7slot_fx6_v2": v2, "dmm7slot_fx6_back": sorted([v2[0]] + v1, key=lambda s: s[0])}


def guards_for(cfg, sites, table):
    """Bytes beside the sites, from the file: the rest of every touched record, the end markers before and after the 4K layout's planes,
    and the three parent records. Each at most 16 bytes, inside one record, never on a site."""
    R, data, at = table
    site_at = {a for a, *_ in sites}
    out = []

    def add(addr, n, note):
        assert 0 < n <= 16 and not any(addr < s + 4 and s < addr + n for s in site_at)
        seq, off = divmod(addr - R, 0x14)
        assert off + n <= 0x14
        out.append({"ram_address": hex(addr), "bytes": data[addr - R:addr - R + n].hex(), "file_offset": hex(at[seq] + off), "note": note})

    seen = set()
    for _, _, _, u, _ in sites:
        if u["seq"] in seen:
            continue
        seen.add(u["seq"])
        rec = R + u["seq"] * 0x14
        free = [rec + 4 * k for k in range(5) if rec + 4 * k not in site_at]
        runs = [[free[0]]]
        for w in free[1:]:
            if w == runs[-1][-1] + 4:
                runs[-1].append(w)
            else:
                runs.append([w])
        for run in runs:
            add(run[0], 4 * len(run), "layout %#x, key %#x record at %#x: the words this design leaves alone, as in the file" % (u["group"]["gid"], u["key"], rec))
    g_4k = next(g for g in cfg.groups if g["gid"] == UHD_GROUP)
    first, last = g_4k["units"][0]["seq"], g_4k["units"][-1]["seq"]
    for seq, what in ((first - 1, "the end marker before the 4K layout's planes"), (last + 1, "the end marker after the 4K layout's planes")):
        assert data[seq * 0x14 + 8:seq * 0x14 + 12] == b"\xff" * 4
        add(R + seq * 0x14, 16, what)
    for u in cfg.units_by_key[PARENT]:
        add(R + u["seq"] * 0x14, 16, "parent block, key 0x39 in layout %#x: 106,954,752 bytes, as in the file" % u["group"]["gid"])
    return out


def fits(cfg, sites):
    """Each of the two layouts with the design's sizes: total, parent, spare."""
    R = P.RAM[BUILD]["unit_records"]
    size = {a: struct.unpack("<I", n)[0] for a, o, n, u, _ in sites if a == R + u["seq"] * 0x14 + 12}
    out = {}
    for gid in (HD_GROUP, UHD_GROUP):
        g = next(g for g in cfg.groups if g["gid"] == gid)
        total = sum(size.get(R + u["seq"] * 0x14 + 12, u["size"]) for u in g["units"])
        out[hex(gid)] = {"total": total, "parent": PARENT_SIZE, "spare": PARENT_SIZE - total}
    return out


def emulate(cfg, words):
    """The FX6's own allocator: what requests for an output plane (id 0x2d9) get, in the states a camera can be in when the words land."""
    def fresh():
        s = E.Server(cfg.data, cfg)
        assert s.init() == 0
        return s

    def write(s):
        for a, _, n, *_ in words:
            s.uc.mem_write(a, n)

    def opens(s, n):
        out = []
        for _ in range(n):
            e = s.open(MEM_ID)
            out.append(e["extents"][0]["size"] if e["ok"] else e["result"].split(" (")[0])
        return out

    def brief(lst):
        runs = []
        for x in lst:
            if runs and runs[-1][0] == x:
                runs[-1][1] += 1
            else:
                runs.append([x, 1])
        return [("%d x %s" % (n, f"{x:,}" if isinstance(x, int) else x)) for x, n in runs]

    res = {}
    s = fresh()
    write(s)
    res["nothing open when written"] = brief(opens(s, 20))
    for n in (9, 17):
        s = fresh()
        opens(s, n)
        write(s)
        base = len(s.opens) - n
        assert all(s.free(base + k)["ok"] for k in range(n))
        res["%d planes open when written, all released, then asked again" % n] = brief(opens(s, 20))
    s = fresh()
    opens(s, 9)
    write(s)
    base = len(s.opens) - 9
    assert all(s.free(base + k)["ok"] for k in range(1, 9))
    res["9 planes open when written, all but the first (the HD layout's) released, then asked again"] = brief(opens(s, 20))
    s = fresh()
    opens(s, 9)
    write(s)
    res["9 planes open when written, more asked without a release"] = brief(opens(s, 20))
    return res


def main():
    E.use_build(BUILD)
    cfg = P.Config(P.find_file(BUILD), BUILD)
    sha = hashlib.sha256(cfg.data).hexdigest()
    img = next(p for p in (ROOT / "work/extracted" / BUILD).rglob("cpapp-b.bin") if "nflasha8" in p.as_posix()).read_bytes()
    table = ram_table(cfg)
    base, data, at = table
    des = designs(cfg)
    assert [a for a, *_ in des["dmm7slot_fx6_v1"]] == ISSUE2, "not the tester's ten addresses"
    # 0x7fd: below the reader's limit, in no record of the file and in no id row
    assert SPARE_KEY < KEY_LIMIT and SPARE_KEY not in cfg.units_by_key and SPARE_KEY not in cfg.region_by_key
    assert not any(SPARE_KEY in r["keys"] for r in cfg.ids)
    in_image = sum(1 for o in range(0, len(img) - 3, 4) if img[o:o + 4] == w32(SPARE_KEY))
    # the tester's dumps: the camera's table equals the file, and the second dump differs from the first in exactly v1's ten words
    dump = {tag: (DUMPS / f"dmm_table_0213e000_{tag}.bin") for tag in ("stock", "applied")}
    checked = {"dumps_present": all(p.exists() for p in dump.values())}
    if checked["dumps_present"]:
        dump = {tag: p.read_bytes() for tag, p in dump.items()}
        off = base - DUMP_BASE
        assert dump["stock"][off:off + len(data)] == data, "the camera's table is not the file's"
        diff = [DUMP_BASE + o for o in range(0, 0x7000, 4) if dump["stock"][o:o + 4] != dump["applied"][o:o + 4]]
        assert diff == ISSUE2
        for a, o, n, *_ in des["dmm7slot_fx6_v1"]:
            assert dump["stock"][a - DUMP_BASE:a - DUMP_BASE + 4] == o and dump["applied"][a - DUMP_BASE:a - DUMP_BASE + 4] == n
        checked.update(records_equal_to_the_file=len(data) // 0x14, table_span=[hex(base), hex(base + len(data))],
                       words_that_differ_between_the_dumps=[hex(a) for a in diff],
                       stock_dump_sha256=hashlib.sha256(dump["stock"]).hexdigest(), applied_dump_sha256=hashlib.sha256(dump["applied"]).hexdigest())
    for a, o, n, u, _ in sum(des.values(), []):
        assert data[a - base:a - base + 4] == o and o != n and a % 4 == 0
    # the allocator
    stock = emulate(cfg, [])
    assert stock["nothing open when written"] == ["17 x 13,271,040", "3 x no group offers the key now"]
    emu = {"stock": stock}
    for name in NAMES:
        emu[name] = emulate(cfg, des[name])
    alone = "the 4K layout's nine words alone (not shipped)"
    emu[alone] = emulate(cfg, [s for s in des["dmm7slot_fx6_v1"] if s[3]["group"]["gid"] == UHD_GROUP])
    full = "9 planes open when written, all released, then asked again"
    assert emu["dmm7slot_fx6_v1"][full] == ["1 x refused", "14 x 14,745,600", "5 x no group offers the key now"]
    assert emu["dmm7slot_fx6_v2"][full] == ["14 x 14,745,600", "6 x no group offers the key now"]
    assert emu[alone][full][0] == "1 x 13,271,040"
    for name in NAMES:
        for k, v in emu[name].items():
            assert not any("13,271,040" in x for x in v), (name, k, v)   # no small plane is ever handed out once the words are in
    fit = {name: fits(cfg, des[name]) for name in NAMES}
    assert fit["dmm7slot_fx6_v1"]["0x28"]["spare"] == 3_731_456 and fit["dmm7slot_fx6_v1"]["0x26"]["spare"] == -688_128
    assert fit["dmm7slot_fx6_v2"]["0x28"]["spare"] == 3_731_456 and fit["dmm7slot_fx6_v2"]["0x26"]["spare"] == 786_432
    title = {"dmm7slot_fx6_v1": "Output planes for 2560 rows, the tester's ten words: seven 4K-layout planes of 14,745,600 bytes, the eighth out of the pool, and the HD layout's plane enlarged",
             "dmm7slot_fx6_v2": "Output planes for 2560 rows, variant: seven 4K-layout planes of 14,745,600 bytes, the eighth and the HD layout's plane out of the pool",
             "dmm7slot_fx6_back": "PUT BACK ONLY: every word of dmm7slot_fx6_v1 and dmm7slot_fx6_v2 (eleven), so one put-back restores either"}
    status = {"dmm7slot_fx6_v1": "RAN ON AN FX6 (repo issue 2, 2026-11-26: the ten words written first, then the sensor, encoder, screen and output-size steps; clean 3840 x 2560 XAVC-I 23.98p clips). The tester's library carried nine guards; this design carries more",
              "dmm7slot_fx6_v2": "built from the firmware's file and run in the FX6's own allocator; NEVER RUN ON A CAMERA",
              "dmm7slot_fx6_back": "for the put-back library only (level 17 writes the old bytes where a site holds the new ones and skips a site that is already stock)"}
    for name, sites in des.items():
        d = {"design": name, "build": BUILD, "camera": "ILME-FX6 (FX6), firmware 6.02", "kind": "ram_words", "title": title[name], "status": status[name],
             "credit": "the memory model, the seven-plane idea and the ten words of dmm7slot_fx6_v1: github.com/ArcaneLantern/fx6-open-gate-test issue 2 (Mininoob)",
             "artifact": "DmmCfg.bin (the coprocessor's copy: /cp, partition nflasha8)", "dmmcfg_sha256": sha, "generated_by": "build/build_dmm_fx6.py",
             "table": "unit records %#x .. %#x (parse_dmmcfg.RAM fx6_602): record = base + seq x 0x14, {0, type, key, size, attributes}" % (base, base + len(data)),
             "why": "the FX6 fills an output plane at 1.5 bytes per pixel: 13,271,040 bytes hold 3840 x 2304; 3840 x 2560 needs 14,745,600",
             "sites": [{"ram_address": hex(a), "old": o.hex(), "new": n.hex(), "file_offset": hex(at[u["seq"]] + (a - base) % 0x14), "note": note} for a, o, n, u, note in sites],
             "guards": guards_for(cfg, sites, table),
             "precondition": "the camera has started (the table is copied from the file at start-up). Written during a USB session; it counts from the next time the parent block is divided, which the picture restart at the end of the session brings about (seen on the tester's FX6)",
             "restore": "the old words (step D17), or a cold boot: the table is rebuilt from the file at every start",
             "while_applied": ["14 output planes instead of 17 (two 4K layouts of seven)", "shoot QFHD only; HD, DCI 4K and S&Q are not tested with it"],
             "spare_key": {"key": hex(SPARE_KEY), "below_the_reader_limit": hex(KEY_LIMIT), "in_the_file": False, "aligned_words_of_cpapp_with_this_value": in_image}}
        if name != "dmm7slot_fx6_back":
            d["layouts_after"] = fit[name]
            d["allocator"] = emu[name]
            d["not_shown"] = ["XAVC-L and 25p with it on a camera", "what the camera's picture pipeline does with a refused request - the tester's camera ran"] if name.endswith("v1") else \
                ["anything on a camera", "that nothing else needs the HD layout's 4K plane (no memory id but 0x2d9 names key 0x3f1; the layout's 28 small planes have no id at all)"]
        (ROOT / f"modding/designs/{name}.json").write_text(json.dumps(d, indent=1) + "\n", encoding="utf8", newline="\n")
        print(name, len(d["sites"]), "sites,", len(d["guards"]), "guards")
    ev = {"build": BUILD, "dmmcfg_sha256": sha, "generated_by": "build/build_dmm_fx6.py", "memory_id": hex(MEM_ID), "key": hex(KEY),
          "allocator": "cpapp-b.bin's own DMM module run alone (build/emu_dmm_server.py, fx6_602): one CPU, requests made as plain calls, no other user of the parent block",
          "tester_dumps": checked, "layouts": fit, "requests_for_an_output_plane": emu,
          "reading": ["stock: 17 planes of 13,271,040; the first comes from the HD layout 0x26 (file order), then two 4K layouts of eight",
                      "v1: after a full release the first request is refused (layout 0x26 no longer fits); every later one gets 14,745,600; 14 planes",
                      "v2: no refusal; 14 planes of 14,745,600",
                      "the nine words alone: the HD layout's 13,271,040-byte plane is handed out first, among the big ones"]}
    (ROOT / "evidence/fx6/dmm7slot_fx6_emu.json").write_text(json.dumps(ev, indent=1) + "\n", encoding="utf8", newline="\n")
    for name, r in emu.items():
        print(name)
        for k, v in r.items():
            print("   %-90s %s" % (k, v))
    print("layouts:", fit)
    print("tester dumps:", {k: v for k, v in checked.items() if "sha" not in k and k != "words_that_differ_between_the_dumps"})


if __name__ == "__main__":
    main()
