"""Run the built FX6 write libraries in Unicorn against a model camera. Offline; no camera.

  C:/Python313/python.exe -B emu_fx6_write.py

The FX6 6.02 counterpart of helper_fx3/emu_fx3_write.py (made from it, 2026-11-26). The libraries are helper/readcheck.c's levels 5/6,
16/17 and 19/20 built with this camera's tables (build_fx6_write.sh). The harness is the A7 IV one (helper/emu_built.py); the coprocessor
model is this file's: a transfer must be whole 64-byte lines to or from the allocated buffer, and a transfer TOWARDS the coprocessor may
change only bytes of a listed site, and only to that site's stock or new bytes. Anything else fails the run.

Cases, coprocessor (sensor sites + stored record; output-size word):
  apply on stock -> every site new, nothing else changed;  apply again -> nothing to do;  put back -> all stock
  a site holding foreign bytes -> nothing written;  a write that is lost -> everything this run wrote is put back
  the stored record not where the pointers lead -> nothing written;  a guard byte wrong -> nothing written
  the stored record as an A7S III camera held it (the FX6's stock record of 0x8c0 is the FX3's and the A7S III's byte for byte)
Cases, main processor (encoder sites): apply, apply again, put back; a guard wrong; a lost write in libmpr.so; the kernel's view not
following a write; the step without the header heights (N19) and L19 / L20 over it.
The LCD libraries (S16/S17 = levels 16/17 with the screen design's words) run in the same harness, on the words of the loaded image.
The output-plane memory libraries (D16 / R16 = level 16 with the words of dmm7slot_fx6_v1 / _v2, D17 = level 17 with the words of both;
added after the testers' first runs) run on a model whose RAM holds the camera's copy of DmmCfg.bin's unit records (rebuilt from the file by
build/build_dmm_fx6.py; a tester's dump equals it): apply, apply again, put back; each guard wrong; the table one record further on; no
table; a word holding another size; lost writes; one variant on a camera holding the other (refused); D17 on a stock camera.
Safety cases: the FX3 kit's and the A7S III kit's own write libraries (levels 5, 16 with their screen words, and 19) on an FX6 write nothing,
and neither do the ZV-E1 and FX2 kits' memory libraries (level 13).
"""
import json
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "helper"))
sys.path.insert(0, str(HERE))
import emu_built as E  # noqa: E402
from unicorn import arm64_const as R  # noqa: E402

BASE, CP_HI = 0x108000, 0x10000000
DES = ROOT / "modding/designs"
KIT = json.loads((HERE / "kit.json").read_text(encoding="utf8"))
IMAGER, CTRL, OBJ, CTRL_DRVPARAM = 0x14A5AEC, 0x1500000, 0x1500800, 0x664
IDS, RECS, REC, INDEX, COUNT = 0xE009FC, 0x2196504, 0x15C, 12, 40
VTABLE8, CROP = 0xE02288, 0xE00A9C
SIZE_LO, SIZE_HI = 0x1626000, 0x1627000
LM_AT = 0x7F82D15000
RESULT = E.RESULT


def ex(rel, build="fx6_602"):
    return (ROOT / "work/extracted" / build / "0700_part_image/dev" / rel).read_bytes()


def design(name):
    return json.loads((DES / f"{name}.json").read_text(encoding="utf8"))


class Mem:
    """Coprocessor memory: the image at 0x108000, zeros elsewhere, with what the model camera adds."""

    def __init__(self, image):
        self.pages, self.image = {}, image

    def page(self, a):
        a &= ~0xFFF
        if a not in self.pages:
            p = bytearray(4096)
            if BASE <= a < BASE + len(self.image):
                chunk = self.image[a - BASE:a - BASE + 4096]
                p[:len(chunk)] = chunk
            self.pages[a] = p
        return self.pages[a]

    def read(self, a, n):
        return bytes(self.page(a + k)[(a + k) & 0xFFF] for k in range(n))

    def write(self, a, data):
        for k, v in enumerate(data):
            self.page(a + k)[(a + k) & 0xFFF] = v

    def snapshot(self):
        return {a: bytes(p) for a, p in self.pages.items()}


def camera(image, og, oz):
    m = Mem(image)
    m.write(IMAGER, struct.pack("<I", CTRL))
    m.write(CTRL + CTRL_DRVPARAM, struct.pack("<I", OBJ))
    m.write(OBJ, struct.pack("<6I", VTABLE8, COUNT, IDS, 0, RECS, CROP))
    for i in range(COUNT):
        m.write(RECS + i * REC, bytes([i]) * REC)
    m.write(RECS + INDEX * REC, bytes.fromhex(og["stored_record"]["stock"]))
    for g in oz["guards"]:
        m.write(int(g["ram_address"], 16), bytes.fromhex(g["bytes"]))
    for s in oz["sites"]:
        m.write(int(s["ram_address"], 16), bytes.fromhex(s["old"]))
    return m


def allowed_sites(og, oz):
    """{address: (stock byte, new byte)} for every byte a write may change."""
    out = {}
    for p in og["patches"]:
        a = int(p["addr"], 16)
        for k, (o, n) in enumerate(zip(bytes.fromhex(p["old"]), bytes.fromhex(p["new"]))):
            out[a + k] = (o, n)
    st, nw = bytes.fromhex(og["stored_record"]["stock"]), bytes.fromhex(og["stored_record"]["design"])
    for k in range(REC):
        if st[k] != nw[k]:
            out[RECS + INDEX * REC + k] = (st[k], nw[k])
    for s in oz["sites"]:
        a = int(s["ram_address"], 16)
        for k, (o, n) in enumerate(zip(bytes.fromhex(s["old"]), bytes.fromhex(s["new"]))):
            out[a + k] = (o, n)
    return out


class Run(E.Run):
    def __init__(self, lib, files, dirs, mem, allowed, lose=None):
        super().__init__(lib, 5, files, dirs, cp=b"")           # level 5: the harness's system-call rules for a coprocessor write level
        self.mem, self.allowed, self.lose, self.n_writes = mem, allowed, lose, 0

    def go(self):
        self.uc.reg_write(R.UC_ARM64_REG_SP, E.STACK - 0x1000)
        self.uc.reg_write(R.UC_ARM64_REG_X30, E.RET)
        self.uc.emu_start(self.ctor, E.RET, count=2_000_000_000)
        if not self.bad and self.uc.reg_read(R.UC_ARM64_REG_PC) != E.RET:
            self.bad = "the constructor did not return"
        return self

    def on_import(self, uc, address, size, _):
        x = lambda n: uc.reg_read(getattr(R, "UC_ARM64_REG_X%d" % n))
        name, ret = self.imports.get(address), 0
        if name == "_Z9dmm_allocjPj":
            uc.mem_write(x(1), struct.pack("<I", E.BUF_HANDLE))
            ret = self.buf
        elif name == "_Z8dmm_freej":
            pass
        elif name == "sen_dma_transfer":
            d, src, dst, n = x(0) & 0xFFFFFFFF, x(1), x(2), x(3) & 0xFFFFFFFF
            cp = src if d == 0 else dst
            self.lib_calls.append(("transfer", d, src, dst, n))
            if d not in (0, 1) or (dst if d == 0 else src) != self.buf or cp & 63 or n & 63 or not 0 < n <= 4096 or cp < BASE or cp + n > CP_HI:
                self.bad = "a transfer that is not whole lines to or from the buffer: dir %d src %#x dst %#x size %d" % (d, src, dst, n)
                uc.emu_stop()
                return
            va = next(v for v, off in self.map_phys.items() if v in self.maps and off <= self.buf < off + self.maps[v]) + self.buf % 4096
            if d == 0:
                uc.mem_write(va, self.mem.read(cp, n))
            else:
                data, now = bytes(uc.mem_read(va, n)), self.mem.read(cp, n)
                for k in range(n):
                    if data[k] != now[k] and data[k] not in self.allowed.get(cp + k, ()):
                        self.bad = "a write that changes %#x to %#x, which is not a listed site's stock or new byte" % (cp + k, data[k])
                        uc.emu_stop()
                        return
                self.n_writes += 1
                if self.lose != self.n_writes:               # lose: this write reports success and nothing arrives
                    self.mem.write(cp, data)
        else:
            self.bad = "call of an unexpected import %r" % name
            uc.emu_stop()
            return
        uc.reg_write(R.UC_ARM64_REG_X0, ret)
        uc.reg_write(R.UC_ARM64_REG_PC, uc.reg_read(R.UC_ARM64_REG_X30))


def main():
    fail = []
    ok = lambda cond, text: (print(("PASS  " if cond else "FAIL  ") + text), fail.append(text) if not cond else None)
    lib = lambda L: (HERE / f"libJit_fx6_L{L}.so").read_bytes()
    og, oz, fl = design("ogsq_fx6_v1"), design("outsz2560_fx6_v1"), design(KIT["encoder"])
    fl1 = design(KIT["encoder_v1"]) if KIT.get("encoder_v1") else None
    image = ex("nflasha8/cpapp-b.bin")
    allowed = allowed_sites(og, oz)
    files = E.tree()
    files["/dev/mem"] = b""
    dirs = {"/tmp_wbshd", "/sys/module/liro/parameters", "/proc/driver/pcie"}

    def state(mem):
        """'stock', 'new', or 'mixed' over the bytes of the two coprocessor designs' sites, by design."""
        out = {}
        for nm, keys in (("og", [a for a in allowed if not SIZE_LO <= a < SIZE_HI]), ("oz", [a for a in allowed if SIZE_LO <= a < SIZE_HI])):
            vals = [mem.read(a, 1)[0] for a in keys]
            out[nm] = "stock" if all(v == allowed[a][0] for v, a in zip(vals, keys)) else "new" if all(v == allowed[a][1] for v, a in zip(vals, keys)) else "mixed"
        return out

    def others_unchanged(mem, before):
        for a, p in mem.pages.items():
            b = before.get(a, bytes(4096) if not BASE <= a < BASE + len(image) else image[a - BASE:a - BASE + 4096].ljust(4096, b"\0"))
            if any(p[k] != b[k] and (a + k) not in allowed for k in range(4096)):
                return False
        return True

    def go(L, mem, **kw):
        r = Run(lib(L), files, dirs, mem, allowed, **kw).go()
        return r, r.writes.get(RESULT, b"").decode("utf8", "replace")

    # ---- coprocessor: sensor sites and stored record (levels 5, 6)
    mem = camera(image, og, oz)
    before = mem.snapshot()
    r, t = go(5, mem)
    ok(not r.bad and "DONE: all " in t and "sites hold the target bytes (apply)" in t and state(mem)["og"] == "new" and state(mem)["oz"] == "stock" and others_unchanged(mem, before),
       "level 5 on a stock camera: every site and the stored record's design bytes are new, nothing else changed (%d line writes)" % r.n_writes)
    r, t = go(5, mem)
    ok(not r.bad and "NOTHING TO DO" in t and r.n_writes == 0, "level 5 again: nothing to do, no write")
    r, t = go(6, mem)
    ok(not r.bad and "(put back)" in t and "DONE" in t and state(mem) == {"og": "stock", "oz": "stock"} and mem.snapshot() == {a: before.get(a, mem.snapshot()[a]) for a in mem.pages},
       "level 6: everything is stock again, byte for byte")
    mem = camera(image, og, oz)
    a0 = int(og["patches"][0]["addr"], 16)
    mem.write(a0, b"\x55")
    r, t = go(5, mem)
    ok(not r.bad and r.n_writes == 0 and "holds neither the stock nor the new bytes; nothing is written" in t, "level 5 with one site holding other bytes: nothing is written")
    for lose in (1, 9, 21):
        mem = camera(image, og, oz)
        before = mem.snapshot()
        r, t = go(5, mem, lose=lose)
        ok(not r.bad and "NOT DONE: a step failed; every site this run touched was put back" in t and state(mem)["og"] == "stock" and others_unchanged(mem, before),
           "level 5 with line write %d lost: reported, and every site put back" % lose)
    mem = camera(image, og, oz)
    mem.write(OBJ + 0x10, struct.pack("<I", 0))
    r, t = go(5, mem)
    ok(not r.bad and r.n_writes == 0 and "the stored record was not found" in t, "level 5 with a null records pointer: nothing is written")
    mem = camera(image, og, oz)
    mem.write(CTRL + 0x698, struct.pack("<I", OBJ))       # the FX3's offset holds the object, the FX6's does not: the FX6 library must not follow +0x698
    mem.write(CTRL + CTRL_DRVPARAM, struct.pack("<I", 0))
    r, t = go(5, mem)
    ok(not r.bad and r.n_writes == 0 and "the stored record was not found" in t, "level 5 with the pointer only at the FX3's offset (+0x698): nothing is written")
    mem = camera(image, og, oz)
    mem.write(RECS + INDEX * REC + 6, b"\x07")
    r, t = go(5, mem)
    ok(not r.bad and r.n_writes == 0 and "nothing is written" in t, "level 5 with the stored record's ratio byte not stock: nothing is written")

    # ---- the stored record as the tester's A7S III held it (2026-11-21): run-time bytes differ from the emulated record, the design bytes do not.
    # The FX6's stock record of 0x8c0 is byte-identical to the FX3's and the A7S III's (build/build_og_fx6.py), so that camera's record stands in.
    ev = ROOT / "evidence/a7s3/tester_2026-11-21"
    seen = []
    for run in ("CT6_20261121T132137Z_s3_check", "CT6_20261121T132551Z_s3_dump", "CT6_20261121T134754Z_s3_dump"):
        p = ev / run / "readcheck_result.txt"
        if p.is_file():
            line = next((ln for ln in p.read_text(encoding="utf8", errors="replace").split("\n") if ln.startswith("other stored_record ")), None)
            if line:
                seen.append((run, bytes.fromhex(line.split(" ")[2])))
    for run, record in seen:
        mem = camera(image, og, oz)
        mem.write(RECS + INDEX * REC, record)
        before = mem.snapshot()
        r, t = go(5, mem)
        got = mem.read(RECS + INDEX * REC, REC)
        want = bytearray(record)
        for a, (o, n) in allowed.items():
            if RECS + INDEX * REC <= a < RECS + (INDEX + 1) * REC:
                want[a - RECS - INDEX * REC] = n
        ok(not r.bad and "DONE: all " in t and got == bytes(want) and others_unchanged(mem, before),
           "level 5 with the stored record a camera held in %s: applied, and its run-time bytes are left as they were" % run.split("_")[-1])
        r, t = go(6, mem)
        ok(not r.bad and mem.read(RECS + INDEX * REC, REC) == record, "level 6 after it: the camera's record is back, byte for byte")
    if not seen:
        print("NOTE  the tester's results are not here (evidence/a7s3/tester_2026-11-21): the camera-record cases were skipped")

    # ---- coprocessor: the output-size word (levels 16, 17)
    mem = camera(image, og, oz)
    before = mem.snapshot()
    r, t = go(16, mem)
    ok(not r.bad and state(mem) == {"og": "stock", "oz": "new"} and others_unchanged(mem, before) and "!!" not in t.split("== level")[-1], "level 16 on a stock camera: the size word is new, nothing else changed")
    r, t = go(17, mem)
    ok(not r.bad and state(mem) == {"og": "stock", "oz": "stock"}, "level 17: the size word is stock again")
    mem = camera(image, og, oz)
    mem.write(int(oz["guards"][0]["ram_address"], 16), bytes(8))
    r, t = go(16, mem)
    ok(not r.bad and r.n_writes == 0 and state(mem)["oz"] == "stock", "level 16 with the size table not filled (guard zero): nothing is written")

    # ---- main processor: encoder sites (levels 19, 20), with the harness's own model of /dev/mem and /proc/self/mem
    enc_built = (HERE / "libJit_fx6_L19.so").is_file()
    if not enc_built:
        print("NOTE  libJit_fx6_L19.so is not built yet: the encoder cases are skipped (this run does not pass the kit)")
        fail.append("encoder libraries not built")
    av, lm = ex("nflasha3/av-cam.bin"), ex("nflasha15/lib/libmpr.so")
    av = bytes([0x5A]) * 0x1000 + av[0x1000:]            # as on a camera: the first page is not the file's (2026-11-21); no level may depend on it
    phoff, phentsize, phnum = struct.unpack_from("<Q", lm, 0x20)[0], *struct.unpack_from("<HH", lm, 0x36)
    span = next(struct.unpack_from("<IIQQQQQQ", lm, phoff + k * phentsize) for k in range(phnum) if struct.unpack_from("<I", lm, phoff + k * phentsize)[0] == 1)[5]
    lspan = (span + 0xFFF) & ~0xFFF
    lm0 = lm[:span].ljust(lspan, b"\0")
    mfiles = dict(files)
    mfiles["/proc/self/mem"] = b""
    mfiles["/proc/self/maps"] = (b"00400000-00409000 r-xp 00000000 fc:8f 81970                              /usr/bin/im.elf\n"
                                 b"7f5c1e3000-7f6120c000 r-xp 00000000 fc:8f 55369                          /usr/lib/appFw.so\n"
                                 + b"%x-%x r-xp 00000000 fc:8f 55354                          /usr/lib/libmpr.so\n" % (LM_AT, LM_AT + lspan)
                                 + b"%x-%x ---p %08x fc:8f 55354                          /usr/lib/libmpr.so\n" % (LM_AT + lspan, LM_AT + lspan + 0x10000, lspan)
                                 + b"%x-%x r--p %08x fc:8f 55354                          /usr/lib/libmpr.so\n" % (LM_AT + lspan + 0x10000, LM_AT + lspan + 0x19000, lspan)
                                 + b"7f8b936000-7f8b991000 r-xp 00000000 fc:8f 55344                          /usr/lib/libsencore.so\n")

    if enc_built:
        def sites_of(d):
            s = {"av-cam.bin": [], "libmpr.so": []}
            for p in d["patches"]:
                s[p["binary"]].append((int(p["file_off"], 16), bytes.fromhex(p["old"]), bytes.fromhex(p["new"])))
            return s
        sites = sites_of(fl)

        def applied(blob, which, s=sites):
            b = bytearray(blob)
            for o, old, new in s[which]:
                b[o:o + len(new)] = new
            return bytes(b)

        def mp(L, av_mem, lm_mem, **wrong):
            r = (E.Run(lib(L), L, mfiles, dirs, {E.AVCAM_PHYS: av_mem}, own={LM_AT: lm_mem}) if isinstance(L, int) else
                 E.Run((HERE / f"libJit_fx6_{L}.so").read_bytes(), int(L[1:]), mfiles, dirs, {E.AVCAM_PHYS: av_mem}, own={LM_AT: lm_mem}))
            r.kview_fail = wrong.get("kview_fail", False)
            r.stale = {E.AVCAM_PHYS + o for o in wrong.get("stale", ())}
            r.pwrite_lost = {LM_AT + o for o in wrong.get("pwrite_lost", ())}
            r.go()
            return r, r.writes.get(RESULT, b"").decode("utf8", "replace"), bytes(r.phys[E.AVCAM_PHYS]), bytes(r.uc.mem_read(LM_AT, lspan))

        n_av, n_lm = len(sites["av-cam.bin"]), len(sites["libmpr.so"])
        av1, lm1 = applied(av, "av-cam.bin"), applied(lm0, "libmpr.so")
        r, t, a, m = mp(19, av, lm0)
        ok(not r.bad and a == av1 and m == lm1 and "DONE" in t, "level 19 on a stock camera: %d + %d sites new, every other byte of both files' memory unchanged" % (n_av, n_lm))
        r, t, a, m = mp(19, av1, lm1)
        ok(not r.bad and a == av1 and m == lm1 and not r.pwrites and not r.map_writes, "level 19 again: no write")
        r, t, a, m = mp(20, av1, lm1)
        ok(not r.bad and a == av and m == lm0 and "DONE" in t, "level 20: both are stock again, byte for byte")
        for g in KIT["mp_guards"]["av-cam.bin"]:
            bad_av = bytearray(av)
            bad_av[int(g["file_off"], 16)] ^= 1
            r, t, a, m = mp(19, bytes(bad_av), lm0)
            if r.bad or a != bytes(bad_av) or m != lm0 or r.pwrites or r.map_writes:
                ok(False, "level 19 with the av-cam.bin guard %s wrong: nothing is written" % g["name"])
                break
        else:
            ok(True, "level 19 with any one of the %d av-cam.bin guards wrong: nothing is written" % len(KIT["mp_guards"]["av-cam.bin"]))
        for g in KIT["mp_guards"]["libmpr.so"] + [x for cg in fl.get("libmpr_code_guards", []) for x in cg["guards"]]:
            bad_lm = bytearray(lm0)
            bad_lm[int(g["file_off"], 16)] ^= 1
            r, t, a, m = mp(19, av, bytes(bad_lm))
            if r.bad or a != av or m != bytes(bad_lm) or r.pwrites or r.map_writes:
                ok(False, "level 19 with the libmpr.so guard at %s wrong: nothing is written" % g["file_off"])
                break
        else:
            ok(True, "level 19 with any one libmpr.so guard wrong: nothing is written")
        if n_lm:
            r, t, a, m = mp(19, av, lm0, pwrite_lost=[sites["libmpr.so"][0][0]])
            ok(not r.bad and a == av and m == lm0 and "NOT DONE: a step failed; every site this run touched was put back" in t, "level 19 with a libmpr.so write lost: everything put back")
        if n_av > 3:
            r, t, a, m = mp(19, av, lm0, stale=[sites["av-cam.bin"][3][0]])
            ok(not r.bad and a == av and m == lm0 and "NOT DONE: a step failed; every site this run touched was put back" in t, "level 19 with the kernel's view not following a write: everything put back")
        if fl1:
            s1 = sites_of(fl1)
            av1n, lm1n = applied(av, "av-cam.bin", s1), applied(lm0, "libmpr.so", s1)
            r, t, a, m = mp("N19", av, lm0)
            ok(not r.bad and a == av1n and m == lm1n and "DONE" in t, "N19 (without the header heights) on a stock camera: its sites only")
            r, t, a, m = mp(19, av1n, lm1n)
            ok(not r.bad and a == av1 and m == lm1 and "DONE" in t, "L19 on a camera holding N19: the header sites are added, nothing else changes")
            r, t, a, m = mp(20, av1n, lm1n)
            ok(not r.bad and a == av and m == lm0 and "DONE" in t, "L20 on a camera holding N19: stock again")

    # ---- the LCD step, coprocessor words inside the loaded image (S16, S17)
    if KIT.get("screen"):
        named = lambda n: (HERE / f"libJit_fx6_{n}.so").read_bytes()
        lf = design(KIT["screen"])
        lf_allowed = {}
        for st in lf["sites"]:
            a0 = int(st["ram_address"], 16)
            for k, (o, n) in enumerate(zip(bytes.fromhex(st["old"]), bytes.fromhex(st["new"]))):
                lf_allowed[a0 + k] = (o, n)

        def go_s(n, mem, **kw):
            r = Run(named(n), files, dirs, mem, lf_allowed, **kw).go()
            return r, r.writes.get(RESULT, b"").decode("utf8", "replace")

        def lf_state(mem):
            vals = [(mem.read(a, 1)[0], pair) for a, pair in lf_allowed.items()]
            return "stock" if all(v == pr[0] for v, pr in vals) else "new" if all(v == pr[1] for v, pr in vals) else "mixed"

        def image_but(mem, addrs):
            for a, pg in mem.pages.items():
                b = image[a - BASE:a - BASE + 4096].ljust(4096, b"\0") if BASE <= a < BASE + len(image) else bytes(4096)
                if any(pg[k] != b[k] and (a + k) not in addrs for k in range(4096)):
                    return False
            return True

        mem = Mem(image)
        r, t = go_s("S16", mem)
        ok(not r.bad and "DONE: every site holds the target bytes (apply)" in t and lf_state(mem) == "new" and image_but(mem, lf_allowed) and r.n_writes == len(lf["sites"]),
           "S16 on the stock image: the %d words are new, every other byte is the image's (%d line writes)" % (len(lf["sites"]), r.n_writes))
        r, t = go_s("S16", mem)
        ok(not r.bad and "NOTHING TO DO" in t and r.n_writes == 0, "S16 again: nothing to do, no write")
        r, t = go_s("S17", mem)
        ok(not r.bad and "(put back)" in t and "DONE" in t and lf_state(mem) == "stock" and image_but(mem, ()), "S17: the image again, byte for byte")
        for g in lf["guards"]:
            mem = Mem(image)
            ga = int(g["ram_address"], 16)
            mem.write(ga, bytes([mem.read(ga, 1)[0] ^ 1]))
            r, t = go_s("S16", mem)
            if r.bad or r.n_writes or "are not as expected; nothing is written" not in t:
                ok(False, "S16 with the guard at %#x wrong: nothing is written" % ga)
                break
        else:
            ok(True, "S16 with any one of the %d guards wrong: nothing is written" % len(lf["guards"]))
        mem = Mem(image)
        mem.write(int(lf["sites"][2]["ram_address"], 16), b"\x02\x00\x00\x00")
        r, t = go_s("S16", mem)
        ok(not r.bad and r.n_writes == 0 and "holds neither the earlier nor the new bytes; nothing is written" in t, "S16 with one word holding other bytes: nothing is written")
        for lose in sorted({1, 2, len(lf["sites"]) // 2, len(lf["sites"])}):
            mem = Mem(image)
            r, t = go_s("S16", mem, lose=lose)
            ok(not r.bad and "NOT DONE: a step failed; every site this run touched was put back" in t and lf_state(mem) == "stock" and image_but(mem, ()),
               "S16 with line write %d lost: reported, and every word put back" % lose)

    # ---- the output-plane memory step: words of the camera's run-time copy of DmmCfg.bin, beyond the image (D16, R16; D17 puts back either)
    if KIT.get("dmm"):
        named = lambda n: (HERE / f"libJit_fx6_{n}.so").read_bytes()
        sys.path.insert(0, str(ROOT / "build"))
        import build_dmm_fx6 as B
        cfg = B.P.Config(B.P.find_file("fx6_602"), "fx6_602")
        tbase, table, _ = B.ram_table(cfg)
        d1, d2, db = design(KIT["dmm"]), design(KIT["dmm_alt"]), design(KIT["dmm_back"])
        dm_allowed = {int(s["ram_address"], 16) + k: (o, n) for s in db["sites"] for k, (o, n) in enumerate(zip(bytes.fromhex(s["old"]), bytes.fromhex(s["new"])))}

        def cam(at=tbase, data=table):
            m = Mem(image)
            if data:
                m.write(at, data)
            return m

        def go_d(n, mem, **kw):
            r = Run(named(n), files, dirs, mem, dm_allowed, **kw).go()
            return r, r.writes.get(RESULT, b"").decode("utf8", "replace")

        def want(d):
            t = bytearray(table)
            for s in (d["sites"] if d else ()):
                a = int(s["ram_address"], 16) - tbase
                assert t[a:a + 4] == bytes.fromhex(s["old"])
                t[a:a + 4] = bytes.fromhex(s["new"])
            return bytes(t)

        def holds(mem, d):
            """The table is the file's with exactly this design's words changed (None: stock), and every other byte of memory is untouched."""
            ref = cam(data=want(d))
            return all(bytes(p) == bytes(ref.page(a)) for a, p in mem.pages.items())

        for step, d in (("D16", d1), ("R16", d2)):
            mem = cam()
            r, t = go_d(step, mem)
            ok(not r.bad and "DONE: every site holds the target bytes (apply)" in t and holds(mem, d) and r.n_writes == len(d["sites"]),
               "%s on the stock table: its %d words are new, every other byte is as before (%d line writes)" % (step, len(d["sites"]), r.n_writes))
            r, t = go_d(step, mem)
            ok(not r.bad and "NOTHING TO DO" in t and r.n_writes == 0, "%s again: nothing to do, no write" % step)
            r, t = go_d("D17", mem)
            ok(not r.bad and "(put back)" in t and "DONE" in t and holds(mem, None), "D17 on a camera holding %s: the file's table again, byte for byte" % d["design"])
            for g in d["guards"]:
                mem = cam()
                ga = int(g["ram_address"], 16)
                mem.write(ga, bytes([mem.read(ga, 1)[0] ^ 1]))
                r, t = go_d(step, mem)
                if r.bad or r.n_writes or "are not as expected; nothing is written" not in t:
                    ok(False, "%s with the guard at %#x wrong: nothing is written" % (step, ga))
                    break
            else:
                ok(True, "%s with any one of the %d guards wrong: nothing is written" % (step, len(d["guards"])))
            mem = cam(at=tbase + 0x14)
            r, t = go_d(step, mem)
            ok(not r.bad and r.n_writes == 0 and "nothing is written" in t, "%s with the table one record further on: nothing is written" % step)
            mem = cam(data=b"")
            r, t = go_d(step, mem)
            ok(not r.bad and r.n_writes == 0 and "nothing is written" in t, "%s with no table there (zeros): nothing is written" % step)
            mem = cam()
            mem.write(int(d["sites"][3]["ram_address"], 16), struct.pack("<I", 12_288_000))
            r, t = go_d(step, mem)
            ok(not r.bad and r.n_writes == 0 and "holds neither the earlier nor the new bytes; nothing is written" in t, "%s with one word holding another size: nothing is written" % step)
            for lose in sorted({1, 2, len(d["sites"]) // 2, len(d["sites"])}):
                mem = cam()
                r, t = go_d(step, mem, lose=lose)
                ok(not r.bad and "NOT DONE: a step failed; every site this run touched was put back" in t and holds(mem, None),
                   "%s with line write %d lost: reported, and every word put back" % (step, lose))
        mem = cam()
        r, t = go_d("D17", mem)
        ok(not r.bad and "NOTHING TO DO" in t and r.n_writes == 0, "D17 on a stock camera: nothing to do, no write")
        for first, second in (("D16", "R16"), ("R16", "D16")):
            mem = cam()
            go_d(first, mem)
            held = d1 if first == "D16" else d2
            r, t = go_d(second, mem)
            ok(not r.bad and r.n_writes == 0 and "nothing is written" in t and holds(mem, held), "%s on a camera holding %s's words: nothing is written (put back first)" % (second, first))
        mem = cam(data=want(d1))
        r, t = go_d("D17", mem, lose=3)
        ok(not r.bad and "NOT DONE: a step failed; every site this run touched was put back" in t and holds(mem, d1),
           "D17 with line write 3 lost: reported, and the camera holds dmm7slot_fx6_v1 again")
        # the other kits' memory libraries (level 13: the raw write buffer of another body's table) on an FX6
        for kit, path in (("ZV-E1", HERE.parent / "helper_zv/libJit_zv_L13.so"), ("FX2", HERE.parent / "helper_fx2/libJit_fx2_L13.so")):
            if not path.is_file():
                print(f"NOTE  {path.name} is not here: the {kit} memory-step safety case was skipped")
                continue
            mem = cam()
            r = Run(path.read_bytes(), files, dirs, mem, {}).go()
            t = r.writes.get(RESULT, b"").decode("utf8", "replace")
            ok(r.n_writes == 0 and holds(mem, None) and ("nothing is written" in t or bool(r.bad)), "the %s kit's memory step (L13) on an FX6: nothing is written" % kit)

    # ---- safety: the FX3 kit's and the A7S III kit's write libraries on an FX6 write nothing (an FX6 owner might run one of those kits; their apply
    # also needs a READY check of their own kit, which an FX6 never gives: helper_fx6/emu_fx6.py). Any write the model sees fails the case.
    for kit, folder, prefix, imager in (("FX3", "helper_fx3", "fx3", 0x127AB68), ("A7S III", "helper_s3", "s3", 0x12A41F0)):
        other = lambda n: (HERE.parent / folder / f"libJit_{prefix}_{n}.so").read_bytes()
        if not (HERE.parent / folder / f"libJit_{prefix}_L5.so").is_file():
            print(f"NOTE  {folder}'s libraries are not here: the {kit} safety cases were skipped")
            continue
        mem = camera(image, og, oz)
        mem.write(imager, struct.pack("<I", CTRL))        # the worst case: that kit's sensor-object address leads to the FX6's real control object
        mem.write(CTRL + 0x698, struct.pack("<I", OBJ))   # and its +0x698 to the FX6's drive-parameter object
        before = mem.snapshot()
        r = Run(other("L5"), files, dirs, mem, {}).go()
        t = r.writes.get(RESULT, b"").decode("utf8", "replace")
        fresh = lambda a: before.get(a, image[a - BASE:a - BASE + 4096].ljust(4096, b"\0") if BASE <= a < BASE + len(image) else bytes(4096))
        same = all(bytes(p) == fresh(a) for a, p in mem.pages.items())
        ok(not r.bad and r.n_writes == 0 and "nothing is written" in t and same,
           "the %s kit's L5 on an FX6 (even with its pointer chain leading to the FX6's object): nothing is written" % kit)
        mem = Mem(image)
        r = Run(other("S16"), files, dirs, mem, {}).go()
        t = r.writes.get(RESULT, b"").decode("utf8", "replace")
        ok(not r.bad and r.n_writes == 0 and "nothing is written" in t and image_but(mem, ()) if KIT.get("screen") else not r.n_writes,
           "the %s kit's S16 on an FX6: nothing is written" % kit)
        r = E.Run(other("L19"), 19, mfiles, dirs, {E.AVCAM_PHYS: av}, own={LM_AT: lm0})
        r.go()
        ok(not r.bad and bytes(r.phys[E.AVCAM_PHYS]) == av and bytes(r.uc.mem_read(LM_AT, lspan)) == lm0 and not r.pwrites and not r.map_writes,
           "the %s kit's L19 on an FX6: nothing is written in av-cam.bin or libmpr.so" % kit)
    print("ALL PASS" if not fail else "FAILED: %d" % len(fail))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
