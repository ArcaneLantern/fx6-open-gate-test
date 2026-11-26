"""Run the built FX6 read-only helper in Unicorn against a model camera. Offline; no camera.

  C:/Python313/python.exe -B emu_fx6.py [--show]

The FX6 6.02 counterpart of helper_fx3/emu_fx3.py (same harness: helper/emu_built.py; the same coprocessor model: only a transfer of
one whole page, direction 0, into the allocated buffer is accepted). Cases, for both libraries (check and dump):
  stock        an FX6 with the 6.02 files and stock memory                         -> every check same, verdict READY
  applied      every design site holding its new bytes, the LCD step included      -> TARGET everywhere, verdict READY
  no-screen    the open-gate state without the LCD step                            -> open-gate TARGET, screen words STOCK, READY
  alt-memory   the open-gate state with the memory step's variant (kit.json "dmm_alt") -> its ten words TARGET, READY
  no-memory    the earlier kit's state: no memory step                              -> the memory words STOCK, the rest TARGET, READY
  no-meta      the encoder step without the file-header heights (if the kit has one) -> its sites TARGET, the heights STOCK, READY
  fx3          the FX3 7.02 files and coprocessor image (the nearest other body)   -> identity DIFFERS, verdict NOT READY
  a7s3         the A7S III 5.01 files and coprocessor image                        -> identity DIFFERS, verdict NOT READY
  no-reserve   a command line without the av-cam reservation                        -> av-cam.bin not read, NOT READY
  exists       a result file already present                                        -> nothing done
and the other way round, the published check libraries of the FX3 kit (helper_fx3), the A7S III kit (helper_s3) and the ZV-E1 kit
(helper_zv) run on a stock FX6: each must say NOT READY (an FX6 owner might run one of those kits; their apply scripts start only after
a READY check). Checks also that nothing but the result file is written and that no transfer has another direction.
"""
import json
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "helper"))
import emu_built as E  # noqa: E402
from unicorn import arm64_const as R  # noqa: E402

BASE = 0x108000
FACTS = json.loads((HERE / "fx6_expected.json").read_text(encoding="utf8"))
KIT = json.loads((HERE / "kit.json").read_text(encoding="utf8"))
DES = ROOT / "modding/designs"
CP_RANGE = (0xC0000, 0x2700000)                 # the widest of the kits' read ranges (ZV-E1 0x2700000): a foreign helper is modelled too


def ex(build, rel):
    return (ROOT / "work/extracted" / build / "0700_part_image/dev" / rel).read_bytes()


def design(name):
    return json.loads((DES / f"{name}.json").read_text(encoding="utf8"))


class Run(E.Run):
    """E.Run with this helper's coprocessor model: cp_image (bytes at 0x108000) and cp_ram {address: bytes} over zeros."""

    def on_import(self, uc, address, size, _):
        x = lambda n: uc.reg_read(getattr(R, "UC_ARM64_REG_X%d" % n))
        name, ret = self.imports.get(address), 0
        if name == "_Z9dmm_allocjPj":
            self.lib_calls.append(("alloc", x(0) & 0xFFFFFFFF))
            uc.mem_write(x(1), struct.pack("<I", E.BUF_HANDLE))
            ret = self.buf
        elif name == "_Z8dmm_freej":
            self.lib_calls.append(("free", x(0) & 0xFFFFFFFF))
        elif name == "sen_dma_transfer":
            direction, src, dst, n = x(0) & 0xFFFFFFFF, x(1), x(2), x(3) & 0xFFFFFFFF
            self.lib_calls.append(("transfer", direction, src, dst, n))
            if direction != 0 or dst != self.buf or n != 4096 or src & 0xFFF or not CP_RANGE[0] <= src < CP_RANGE[1]:
                self.bad = "a transfer that is not a read of one whole page in range: dir %d src %#x dst %#x size %d" % (direction, src, dst, n)
                uc.emu_stop()
                return
            page = bytearray(4096)
            img = self.cp["image"]
            if BASE <= src < BASE + len(img):
                chunk = img[src - BASE:src - BASE + 4096]
                page[:len(chunk)] = chunk
            for a, blob in self.cp["ram"].items():
                lo, hi = max(a, src), min(a + len(blob), src + 4096)
                if lo < hi:
                    page[lo - src:hi - src] = blob[lo - a:hi - a]
            va = next(v for v, off in self.map_phys.items() if v in self.maps and off <= self.buf < off + self.maps[v]) + self.buf % 4096
            uc.mem_write(va, bytes(page))
        else:
            self.bad = "call of an unexpected import %r" % name
            uc.emu_stop()
            return
        uc.reg_write(R.UC_ARM64_REG_X0, ret)
        uc.reg_write(R.UC_ARM64_REG_PC, uc.reg_read(R.UC_ARM64_REG_X30))

    def go(self):
        self.uc.reg_write(R.UC_ARM64_REG_SP, E.STACK - 0x1000)
        self.uc.reg_write(R.UC_ARM64_REG_X30, E.RET)
        self.uc.emu_start(self.ctor, E.RET, count=3_000_000_000)
        if not self.bad and self.uc.reg_read(R.UC_ARM64_REG_PC) != E.RET:
            self.bad = "the constructor did not return (pc %#x)" % self.uc.reg_read(R.UC_ARM64_REG_PC)
        return self


def dmm_table():
    """The camera's run-time copy of DmmCfg.bin's unit records (build/build_dmm_fx6.py rebuilds it from the file; a tester's dump equals it)."""
    sys.path.insert(0, str(ROOT / "build"))
    import build_dmm_fx6 as B
    cfg = B.P.Config(B.P.find_file("fx6_602"), "fx6_602")
    base, data, _ = B.ram_table(cfg)
    return base, bytearray(data)


def model(build="fx6_602", applied=False, screen=True, reserve=True, exists=False, enc=None, dmm="dmm"):
    cp = bytearray(ex(build, "nflasha8/cpapp-b.bin"))
    av = bytearray(ex(build, "nflasha3/av-cam.bin"))
    libs = {n: ex(build, "nflasha15/lib" + n) for n in ("/libmpr.so", "/libsencore.so", "/libJiritsu.so")}
    lm = bytearray(libs["/libmpr.so"])
    og, oz, fl = design("ogsq_fx6_v1"), design("outsz2560_fx6_v1"), design(enc or KIT["encoder"])
    sc = design(KIT["screen"]) if KIT.get("screen") else {"sites": []}
    ram = {}
    if build == "fx6_602":                       # the FX6's RAM tables; a foreign body keeps its own image and zeros
        sr = og["stored_record"]
        ram[int(sr["address"], 16)] = bytes.fromhex(sr["design" if applied else "stock"])
        for g in oz["guards"]:
            ram[int(g["ram_address"], 16)] = bytes.fromhex(g["bytes"])
        for s in oz["sites"]:
            ram[int(s["ram_address"], 16)] = bytes.fromhex(s["new" if applied else "old"])
        if KIT.get("dmm"):                       # the output-plane table; `dmm` names the kit.json design applied to it ("dmm", "dmm_alt") or None
            base, table = dmm_table()
            for s in (design(KIT[dmm])["sites"] if applied and dmm else ()):
                a = int(s["ram_address"], 16)
                assert table[a - base:a - base + 4] == bytes.fromhex(s["old"])
                table[a - base:a - base + 4] = bytes.fromhex(s["new"])
            ram[base] = bytes(table)
    if applied:
        for p in og["patches"]:
            a, new = int(p["addr"], 16), bytes.fromhex(p["new"])
            cp[a - BASE:a - BASE + len(new)] = new
        for p in fl["patches"]:
            o, new = int(p["file_off"], 16), bytes.fromhex(p["new"])
            (lm if p["binary"] == "libmpr.so" else av)[o:o + len(new)] = new
        if screen:
            for s in sc["sites"]:
                a = int(s["ram_address"], 16)
                cp[a - BASE:a - BASE + 4] = bytes.fromhex(s["new"])
    lm_at = 0x7F82D15000
    maps = b"".join(b"%x-%x r-xp 00000000 b3:0f 100 /usr/lib%s\n" % (a, a + ((len(libs[n]) + 0xFFF) & ~0xFFF), n.encode())
                    for n, a in (("/libsencore.so", 0x7F80000000), ("/libJiritsu.so", 0x7F81000000), ("/libmpr.so", lm_at)))
    files = E.tree()
    files["/proc/self/maps"] = maps
    files["/proc/meminfo"] = b"MemTotal: 1 kB\n"
    files["/dev/mem"] = b""
    files["/proc/cmdline"] = b"console=ttynull0 " + (b"memrsv=0x01000000@0x401000000:ex " if reserve else b"") + b"warm.mode=2"
    for n, b in libs.items():
        files["/usr/lib" + n] = b
    dirs = {"/tmp_wbshd", "/proc", "/proc/self", "/sys/module/liro/parameters", "/log", "/log/cp", "/usr/lib"}
    if exists:
        files[E.RESULT] = b"earlier result\n"
    phys = {FACTS["avcam_phys"]: bytes([0x5A]) * 0x1000 + bytes(av[0x1000:]),      # the first page is not as in the file on a camera (A7S III, 2026-11-21)
            E.BUF_PHYS & ~0xFFF: bytes(0x2000)}
    own = {lm_at: bytes(lm)}
    return files, dirs, phys, {"image": bytes(cp), "ram": ram}, own


def run(lib, **kw):
    files, dirs, phys, cp, own = model(**kw)
    r = Run(lib, 22, files, dirs, phys=phys, cp=cp, own=own)      # level 22: the A7 IV harness's rules for a read-only helper that maps /dev/mem
    r.go()
    return r, r.writes.get(E.RESULT, b"").decode("utf8", "replace")


def main():
    ok = True
    screen_n = sum(1 for s in FACTS["cp_sites"] if s["name"].startswith("screen"))
    hard = [s for s in FACTS["cp_sites"] if not s["name"].startswith(("outsize_guard",))]
    dmm_n = sum(1 for s in FACTS["cp_sites"] if s["name"].startswith("dmm"))
    dmm_in = {k: len(design(KIT[k])["sites"]) for k in ("dmm", "dmm_alt") if KIT.get(k)}      # the words one variant changes (the check lists both variants')
    other = dmm_n - dmm_in.get("dmm", 0)         # memory words the default variant leaves stock
    hard = hard[:len(hard) - other] if other else hard
    cases = [("stock", {}, ("VERDICT READY", "STOCK")), ("applied", {"applied": True}, ("VERDICT READY", "TARGET")),
             ("no-screen", {"applied": True, "screen": False}, ("VERDICT READY", "TARGET"))]
    if KIT.get("dmm_alt"):
        cases.append(("alt-memory", {"applied": True, "dmm": "dmm_alt"}, ("VERDICT READY", "TARGET")))
    if KIT.get("dmm"):
        cases.append(("no-memory", {"applied": True, "dmm": None}, ("VERDICT READY", "TARGET")))
    if KIT.get("encoder_v1"):
        cases.append(("no-meta", {"applied": True, "enc": KIT["encoder_v1"]}, ("VERDICT READY", "TARGET")))
    cases += [("fx3", {"build": "fx3_702"}, ("VERDICT NOT READY", "DIFFERS from the 6.02 update")),
              ("a7s3", {"build": "a7s3_501"}, ("VERDICT NOT READY", "DIFFERS from the 6.02 update")),
              ("no-reserve", {"reserve": False}, ("VERDICT NOT READY", "av-cam.bin is not read")), ("exists", {"exists": True}, ())]
    for which in ("check", "dump"):
        lib = (HERE / f"libJit_fx6_{which}.so").read_bytes()
        for case, kw, want in cases:
            r, text = run(lib, **kw)
            problems = []
            if r.bad:
                problems.append("stopped: " + r.bad)
            if set(r.writes) - {E.RESULT}:
                problems.append("wrote other files: %s" % sorted(set(r.writes) - {E.RESULT}))
            if any(c[0] == "transfer" and c[1] != 0 for c in r.lib_calls):
                problems.append("a transfer towards the coprocessor")
            if case == "exists":
                if r.writes or r.lib_calls:
                    problems.append("did something although a result existed")
            else:
                problems += ["missing %r" % w for w in want if w not in text]
                if "== done" not in text:
                    problems.append("result not complete")
                if case == "stock" and ("OTHER" in text.replace("OTHER (not counted", "") or "DIFFERS" in text or "!!" in text.split("== identity")[1]):
                    problems.append("a stock camera is not reported as all stock")
                if case == "applied" and text.count("TARGET") < len(hard) + FACTS["lm_sites"] + FACTS["av_sites"]:
                    problems.append("not every site reported TARGET: %d" % text.count("TARGET"))
                if case == "no-screen":
                    st = sum(1 for ln in text.split("\n") if ln.startswith("site screen") and ln.endswith("  STOCK"))
                    if st != screen_n or text.count("TARGET") < len(hard) - screen_n + FACTS["lm_sites"] + FACTS["av_sites"]:
                        problems.append("no-screen: %d screen words stock (want %d)" % (st, screen_n))
                if case in ("applied", "alt-memory", "no-memory"):
                    want_t = 0 if case == "no-memory" else dmm_in["dmm_alt" if case == "alt-memory" else "dmm"] if dmm_n else 0
                    got_t = sum(1 for ln in text.split("\n") if ln.startswith("site dmm") and ln.endswith("  TARGET"))
                    got_s = sum(1 for ln in text.split("\n") if ln.startswith("site dmm") and ln.endswith("  STOCK"))
                    if (got_t, got_s) != (want_t, dmm_n - want_t):
                        problems.append("%s: %d memory words target, %d stock (want %d and %d)" % (case, got_t, got_s, want_t, dmm_n - want_t))
                if case == "no-meta":
                    v1 = design(KIT["encoder_v1"])
                    keys = {(p["binary"], p["file_off"]) for p in v1["patches"]}
                    extra = [p for p in design(KIT["encoder"])["patches"] if (p["binary"], p["file_off"]) not in keys]
                    stock_lines = sum(1 for ln in text.split("\n") if ln.startswith(("lm ", "av ")) and ln.endswith("STOCK"))
                    if stock_lines != len(extra):
                        problems.append("no-meta: %d encoder sites stock (want the %d header sites)" % (stock_lines, len(extra)))
                if which == "dump" and case == "stock" and text.count("cppage ") != sum(k for _, _, k in FACTS["dump_ranges"]):
                    problems.append("dump pages: %d" % text.count("cppage "))
            n_tr = sum(1 for c in r.lib_calls if c[0] == "transfer")
            print(f"{which:5} {case:10} {'ok' if not problems else 'FAILED'}  result {len(text):7} bytes, {n_tr:3} page reads  {'; '.join(problems)}")
            ok &= not problems
            if "--show" in sys.argv and case == "stock":
                print("\n".join(l[:150] for l in text.split("== identity")[1].splitlines()[:80]))
    # ---- the other kits' check libraries on an FX6
    for kit, path, verdict in (("FX3 kit", HERE.parent / "helper_fx3/libJit_fx3_check.so", "DIFFERS from the 7.02 update"),
                               ("A7S III kit", HERE.parent / "helper_s3/libJit_s3_check.so", "DIFFERS from the 5.01 update"),
                               ("ZV-E1 kit", HERE.parent / "helper_zv/libJit_zv_check.so", "DIFFERS from the 2.02 update")):
        if not path.is_file():
            print(f"foreign {kit}: library not here, skipped")
            continue
        r, text = run(path.read_bytes())
        good = not r.bad and "VERDICT NOT READY" in text and verdict in text and not (set(r.writes) - {E.RESULT})
        print(f"foreign {kit:12} on a stock FX6: {'ok, NOT READY' if good else 'FAILED'}  {r.bad or ''}")
        ok &= good
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
