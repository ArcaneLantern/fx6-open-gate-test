"""Emulated check of the FX6 6.02 encoder-side design `ogfile2560_xavc_fx6_v1` (build/build_ogfile_fx6.py) on the FX6's own code. 2026-11-26.

The FX6 counterpart of build/run_ogfile_emu.py / build/emu_ogfilesi_fx3.py. Stock against changed, the changes made in emulated memory only:
  libmpr      SetEncOpenParam 0x14c85c (static read of its code and relocations): the encoder request's raster comes from the g_videoParamComb row
              (GOT slot 0x108f1d0 -> R_AARCH64_RELATIVE -> 0xcca018); each changed row's raster stock / changed
  av-cam      (Unicorn, AArch64, the FX6's av-cam.bin at its kernel address)
              matcher 0x209898 with a request built from each changed descriptor, at 3840x2160 and 3840x2560, for every request word +0x88 in
              {0..6} (+0x8c = 12, what every FX6 descriptor list holds); the Python model in build_ogfile_fx6.fx6_match against the real matcher for
              every descriptor; every other request of the codecs 5/8 (QFHD, DCI, HD) gives the same answer with and without the design
              memory function 0x201804: the memory ids an XAVC-L / XAVC-I request asks at 3840x2160 (stock) and 3840x2560 (changed)
              start-block builder 0x20559c with each changed profile; clip-format function 0x19e4bc
  codec       the FX6's own vcd_firmware_imola2.bin (it differs from the A7 IV / FX3 file; its channel-memory calculation 0x800663f4 is at the same
              address, its getters 0x18 further on): the need of each changed descriptor at 3840x2560 against the FX6 DmmCfg sizes of the ids
              the memory function asks; the same for every stock QFHD descriptor of the two codecs (self-check)

Nothing here is hardware. Run:  C:\\Python313\\python.exe -B build/emu_ogfile_fx6.py      writes evidence/fx6/ogfile_fx6_emu.json
"""
import json
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import build_ogfile_fx6 as B6  # noqa: E402
import emu_vcd_chmem  # noqa: E402
import locate_file  # noqa: E402
import parse_dmmcfg  # noqa: E402
from run_ogfile_emu import AVB, CTX, REQ, AvCam, pokes  # noqa: E402

BUILD, NAME = "fx6_602", B6.NAME
D = ROOT / "modding" / "designs"
W0, H0, W1, H1 = 3840, 2160, 3840, 2560
FN = {"DESC": AVB + B6.DESC, "MATCH": AVB + 0x209898, "UNITFN": AVB + 0x201804, "BUILDER": AVB + 0x20559C, "CLIPFN": AVB + 0x19E4BC,
      "DMM_OPEN": AVB + 0x210F3C, "LOGF": AVB + 0x261720, "LOGH": AVB + 0x2616E0, "MEMCPY": AVB + 0xD80, "MEMSET": AVB + 0x2F484}


class AvCam6(AvCam):
    """AvCam with the FX6's functions; the request's +0x88 word is a parameter (the A7 IV emulator fixes it at 2)."""

    def request(self, d, w, h, r88=0):
        req = bytearray(0x200)
        struct.pack_into("<HH", req, 0x08, w, h)
        struct.pack_into("<IIII", req, 0x18, d["codec"], d["infr"], d["f0c"], d["codfr"])
        struct.pack_into("<I", req, 0x38, d["f10"])
        struct.pack_into("<IIII", req, 0x74, 0, d["chroma"], d["bitl"], 0)
        struct.pack_into("<II", req, 0x88, r88, d["list"][0])
        return req

    def select(self, d, w, h, r88=0):
        self.uc.mem_write(CTX, b"\0" * 0x2000)
        self.uc.mem_write(REQ, bytes(self.request(d, w, h, r88)))
        idx = self.call(self.fn["MATCH"], CTX, REQ) & 0xFFFFFFFF
        return None if idx == 0xFFFFFFFF else idx

    def unit_ids(self, d, w, h, r88=0):
        ctx = bytearray(0x10000)
        for off in (0x106C, 0x107C, 0x108C, 0x109C, 0xE46C):
            struct.pack_into("<i", ctx, off, -1)
        struct.pack_into("<I", ctx, 0xE128, d["codec"])
        self.uc.mem_write(CTX, bytes(ctx))
        self.uc.mem_write(REQ, bytes(self.request(d, w, h, r88)))
        ret = self.call(self.fn["UNITFN"], CTX, REQ, 0, 0)
        return {"returned": ret & 0xFF, "memory_ids_asked": [hex(i) for i in self.opened], "errors_logged": self.errors()}

    def clip(self, w, h):
        """0x19e4bc(ctx, packet): packet +0x68/+0x6a raster, +0x81 the row's valid byte (1 for the movie rows)."""
        req = bytearray(0x100)
        struct.pack_into("<HH", req, 0x68, w, h)
        req[0x81] = 1
        # the not-found path logs through [[ctx+8]]+8: ctx+8 -> ctx+0x40 -> ctx+0x80
        self.uc.mem_write(CTX, struct.pack("<QQ", 0, CTX + 0x40) + b"\0" * 0x30 + struct.pack("<Q", CTX + 0x80) + b"\0" * 0x80)
        self.uc.mem_write(REQ, bytes(req))
        return self.call(self.fn["CLIPFN"], CTX, REQ)


def apply(img, kind):
    b = bytearray(img)
    for off, nb in pokes(D / f"{NAME}_pokes_{kind}.txt"):
        b[off:off + len(nb)] = nb
    return bytes(b)


def libmpr_request(lm, lm2, design):
    """Static: SetEncOpenParam's raster copy, the GOT slot's relocation to g_videoParamComb, and each changed row before/after."""
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    ins = [(i.address, i.mnemonic, i.op_str) for i in md.disasm(lm[0x14CA08:0x14CA68], 0x14CA08)]
    want = [(0x14CA08, "adrp", "x23, #0x108f000"), (0x14CA18, "ldr", "x23, [x23, #0x1d0]"), (0x14CA58, "ldrh", "w0, [x24, #4]"),
            (0x14CA5C, "strh", "w0, [x19, #0x68]"), (0x14CA60, "ldrh", "w0, [x24, #6]"), (0x14CA64, "strh", "w0, [x19, #0x6a]")]
    code_ok = all(w in ins for w in want)
    # .rela.dyn: find the relocation for the GOT slot 0x108f1d0
    out = subprocess.run(["wsl", "-e", "bash", "-lc", "readelf -rW '/mnt/c/" + str(locate_file.locate(BUILD, "libmpr.so")).replace("\\", "/")[3:] + "' | grep -i '^000000000108f1d0'"],
                         capture_output=True, text=True).stdout.strip()
    rel_ok = "cca018" in out.lower()
    rows = {}
    for p in design["patches"]:
        if p["kind"] == "L1-comb":
            o = int(p["file_off"], 16) - 6
            r = (o - B6.COMB) // 0x18
            rows[str(r)] = {"stock": list(struct.unpack_from("<HH", lm, o + 4)), "changed": list(struct.unpack_from("<HH", lm2, o + 4))}
    return {"set_enc_open_param_copies_row_raster_to_encopen_68_6a": code_ok, "got_0x108f1d0_relocation": out, "relocation_to_g_videoParamComb": rel_ok,
            "rows": rows}


class Firmware6(emu_vcd_chmem.Firmware):
    """The FX6's codec firmware. Its calculation 0x800663f4 starts as the A7 IV's (24 words equal, branch targets and immediates aside) and its
    four getters are the A7 IV's instructions 0x18 bytes further on, so need()'s getter formulas hold."""

    def __init__(self):
        super().__init__()
        self.img = locate_file.locate(BUILD, "vcd_firmware_imola2.bin").read_bytes()
        self.uc.mem_write(emu_vcd_chmem.FW_BASE - emu_vcd_chmem.PHYS, self.img)


def getters_match():
    a7 = locate_file.locate("a7iv_602", "vcd_firmware_imola2.bin").read_bytes()
    f6 = locate_file.locate(BUILD, "vcd_firmware_imola2.bin").read_bytes()

    def mask(w):
        op = w >> 26
        if op in (2, 3):
            return w & 0xFC000000
        if op in (0x0F, 0x09, 0x0D, 0x23, 0x2B, 0x08, 0x24, 0x25, 0x20, 0x21, 0x28, 0x29):
            return w & 0xFFFF0000
        return w
    res = {}
    for name, va, n, shift in (("calc_head", 0x800663F4, 24, 0), ("cd", 0x80067174, 10, 0x18), ("ld", 0x800671A4, 12, 0x18), ("multi", 0x800671D8, 12, 0x18)):
        o = va - 0x80000000
        a = [mask(w) for w in struct.unpack_from("<%dI" % n, a7, o)]
        b = [mask(w) for w in struct.unpack_from("<%dI" % n, f6, o + shift)]
        res[name] = a == b
    return res


def main():
    av = locate_file.locate(BUILD, "av-cam.bin").read_bytes()
    lm = locate_file.locate(BUILD, "libmpr.so").read_bytes()
    design = json.loads((D / f"{NAME}.json").read_text(encoding="utf8"))
    av2, lm2 = apply(av, "avcam"), apply(lm, "libmpr")
    res, checks = {"design": NAME, "build": BUILD, "functions": {k: hex(v - AVB) for k, v in FN.items() if k != "DESC"}}, {}

    # ---- libmpr
    res["encoder_request"] = libmpr_request(lm, lm2, design)
    e = res["encoder_request"]
    checks["libmpr: SetEncOpenParam copies the comb row's raster into EncOpen +0x68/+0x6a; its GOT slot relocates to g_videoParamComb; rows 0 and 9 "
           "3840x2160 -> 3840x2560, row 2 (XAVC-L 4:2:2 10-bit) unchanged"] = (
        e["set_enc_open_param_copies_row_raster_to_encopen_68_6a"] and e["relocation_to_g_videoParamComb"] and sorted(e["rows"]) == ["0", "9"]
        and all(v == {"stock": [W0, H0], "changed": [W1, H1]} for v in e["rows"].values())
        and lm2[B6.COMB + 0x18 * 2:B6.COMB + 0x18 * 3] == lm[B6.COMB + 0x18 * 2:B6.COMB + 0x18 * 3])

    # ---- av-cam matcher
    s, c = AvCam6(av, FN), AvCam6(av2, FN)
    rows = B6.descriptors(av)
    changed = {p["descriptor"] for p in design["descriptors"]}
    sel, good, own = [], True, True
    for p in design["descriptors"]:
        k = p["descriptor"]
        d = s.desc(k)
        for r88 in range(7):
            for infr in (0, 60, 120, 0xFFFFFFFF):
                q = dict(d, infr=infr)
                row = {"descriptor": k, "r88": r88, "request_input_rate": infr, "stock_2160": s.select(q, W0, H0, r88), "stock_2560": s.select(q, W1, H1, r88),
                       "changed_2560": c.select(q, W1, H1, r88), "changed_2160": c.select(q, W0, H0, r88)}
                row["equivalent"] = row["changed_2560"] == row["stock_2160"] and row["stock_2560"] is None and row["changed_2160"] is None
                good &= row["equivalent"]
                if r88 not in (2, 5) and infr == d["infr"]:
                    own &= row["stock_2160"] == k
                sel.append(row)
    res["matcher_group_equivalence"] = {"requests": len(sel), "all_equivalent": good,
                                        "stock_answers": sorted({(x["descriptor"], x["r88"], x["request_input_rate"], x["stock_2160"]) for x in sel
                                                                 if x["r88"] in (0, 2) and x["request_input_rate"] in (0, 120)})}
    checks["matcher 0x209898: for every request of a changed group (request +0x88 0..6, input rate 0/60/120/-1) the changed matcher at 3840x2560 "
           "answers what the stock one answers at 3840x2160, and nothing is reached at the other height"] = good
    checks["matcher 0x209898: with +0x88 outside {2,5}, each changed descriptor is what its own request reaches on a stock camera"] = own
    # what +0x88 = 2/5 does stock (for the record): XAVC-L finds nothing (every XAVC-L QFHD row has +0x24 = 1), XAVC-I finds the 1xxxxx UseCore-2 row
    res["request_88_is_2"] = {str(p["descriptor"]): s.select(dict(s.desc(p["descriptor"]), infr=0), W0, H0, 2) for p in design["descriptors"]}
    # the Python model against the real matcher, every descriptor, both images
    model_ok, n = True, 0
    for r in rows:
        for img_rows, emu in ((rows, s),):
            for r88 in (0, 2):
                m = B6.fx6_match(img_rows, B6.request_of(r, r88=r88))
                u = emu.select(emu.desc(r["k"]), *r["wh"], r88)
                n += 1
                model_ok &= (m == u)
    checks["the design's Python model of the FX6 matcher gives the real matcher's answer for every descriptor's own request (+0x88 = 0 and 2)"] = model_ok
    # every other codec 5/8 request at its own raster: the same answer before and after (other rates, other classes, DCI, HD, XAVC-L 4:2:2)
    groups = {(s.desc(k)["codec"], s.desc(k)["codfr"], s.desc(k)["f10"]) for k in changed}
    same, moved, m = True, [], 0
    for r in rows:
        if r["codec"] not in (5, 8) or r["k"] in changed:
            continue
        d = s.desc(r["k"])
        for r88 in (0, 2):
            a, b = s.select(d, *r["wh"], r88), c.select(d, *r["wh"], r88)
            m += 1
            if a != b:
                moved.append({"descriptor": r["k"], "raster": list(r["wh"]), "r88": r88, "stock": a, "changed": b})
                same = False
        # at 3840x2560 a request outside the changed groups still finds nothing
        if (d["codec"], d["codfr"], d["f10"]) not in groups and c.select(d, W1, H1, 0) is not None:
            moved.append({"descriptor": r["k"], "raster": [W1, H1], "changed": c.select(d, W1, H1, 0)})
            same = False
    res["other_requests"] = {"compared": m, "answers_that_moved": moved}
    checks["every other XAVC-L / XAVC-I request (other rates and classes, XAVC-L 4:2:2, DCI, HD) gives the same answer with and without the design, "
           "and finds nothing at 3840x2560"] = same

    # ---- memory function: it uses the REQUEST's input rate (not the descriptor's), so normal speed (0) and S&Q (60, 120) are asked separately
    mem, u4, u3 = {}, ["0x486", "0x474", "0x47a", "0x477", "0x485"], ["0x473", "0x479", "0x476", "0x485"]
    for p in design["descriptors"]:
        d = s.desc(p["descriptor"])
        for infr in (0, 60, 120):
            q = dict(d, infr=infr)
            mem[f"{p['descriptor']}/{infr}"] = {"family": p["family"], "request_input_rate": infr, "stock_2160": s.unit_ids(q, W0, H0),
                                                "changed_2560": c.unit_ids(q, W1, H1)}
    res["memory_ids"] = mem
    ids = lambda v, k: v[k]["memory_ids_asked"]
    xi0 = [v for v in mem.values() if v["family"] == "xi" and v["request_input_rate"] == 0]
    xl0 = [v for v in mem.values() if v["family"] == "xl" and v["request_input_rate"] == 0]
    s120 = [v for v in mem.values() if v["request_input_rate"] == 120]
    checks["memory function 0x201804, normal speed: XAVC-I at 3840x2560 asks the 4K blocks it asks stock at 3840x2160 (0x486, 0x474, 0x47a, 0x477, 0x485)"] = all(
        ids(v, "stock_2160") == ids(v, "changed_2560") == u4 and not v["changed_2560"]["errors_logged"] for v in xi0)
    checks["memory function 0x201804, normal speed: XAVC-L 4:2:0 at 3840x2560 asks unit type 3 (0x473, 0x479, 0x476, 0x485), the blocks a stock XAVC-L "
           "QFHD S&Q 120 recording asks at 3840x2160"] = all(ids(v, "stock_2160") == u4 and ids(v, "changed_2560") == u3 and not v["changed_2560"]["errors_logged"]
                                                              for v in xl0) and all(ids(v, "stock_2160") == u3 for v in s120 if v["family"] == "xl")
    checks["memory function 0x201804: S&Q 120 at 3840x2560 is refused (log line 0x220, above 995,328,000 pixels a second), stock S&Q 120 at 3840x2160 is not"] = all(
        v["changed_2560"]["errors_logged"] == ["0x220"] and not v["stock_2160"]["errors_logged"] for v in s120)

    # ---- codec memory need (the FX6's codec firmware) against the FX6 DmmCfg
    cfg = parse_dmmcfg.Config(parse_dmmcfg.find_file(BUILD, "setting"), BUILD)

    def size(i):
        us = [u["size"] for k in cfg.id_rows.get(i, {}).get("keys", []) for u in cfg.units_by_key.get(k, [])]
        return max(us) if us else None
    have = {"cd": size(0x486), "ld": size(0x474), "multi": size(0x477)}
    have3 = {"cd": None, "ld": size(0x473), "multi": size(0x476), "es": size(0x479)}
    assert have3["ld"] == have["ld"] and have3["multi"] == have["multi"], (have, have3)        # type 3's LD/multi are the 4K row's sizes on the FX6
    res["getters"] = getters_match()
    fw = Firmware6()

    def dd(img, k):
        o = B6.DESC + k * 0x90
        b = img[o:o + 0x90]
        w, h = struct.unpack_from("<HH", b, 0x7E)
        return {"w": w, "h": h, "use_core": b[0x78], "enc_cd_mode": b[0x7A], "bit_depth": b[0x82], "chroma": b[0x83], "codec_type": b[0x84],
                "pred_mode": b[0x85], "ebc_ld": b[0x86], "ebc_cd": b[0x87], "scan_mode": b[0x89], "roi": b[0x8A]}
    selfchk, fits = [], []
    for r in rows:
        if r["codec"] in (5, 8) and r["wh"] == (W0, H0):
            nd = fw.need(dd(av, r["k"]))
            selfchk.append({"descriptor": r["k"], "need": {x: nd[x] for x in ("cd", "ld", "multi")}, "asserts": nd["asserts"],
                            "fits": nd["cd"] <= have["cd"] and nd["ld"] <= have["ld"] and nd["multi"] <= have["multi"] and not nd["asserts"]})
    for p in design["descriptors"]:
        nd = fw.need(dd(av2, p["descriptor"]))
        fits.append({"descriptor": p["descriptor"], "family": p["family"], "need": {x: nd[x] for x in ("cd", "ld", "multi")}, "asserts": nd["asserts"],
                     "fits": nd["cd"] <= have["cd"] and nd["ld"] <= have["ld"] and nd["multi"] <= have["multi"] and not nd["asserts"]})
    excl = []
    for k in design["excluded"]["descriptors"]:
        a = bytearray(av[B6.DESC + k * 0x90:B6.DESC + (k + 1) * 0x90])
        struct.pack_into("<H", a, 0x80, H1)
        img = bytearray(av)
        img[B6.DESC + k * 0x90:B6.DESC + (k + 1) * 0x90] = a
        nd = fw.need(dd(bytes(img), k))
        excl.append({"descriptor": k, "need_at_2560": {x: nd[x] for x in ("cd", "ld", "multi")},
                     "fits": nd["cd"] <= have["cd"] and nd["ld"] <= have["ld"] and nd["multi"] <= have["multi"]})
    res["codec_memory"] = {"blocks_4k_row": have, "blocks_type3_row": have3, "stock_qfhd_self_check": selfchk, "changed_2560": fits,
                           "excluded_xavc_l_422_at_2560": excl}
    checks["XAVC-L 4:2:2 10-bit (left out of the design) would not fit at 3840x2560: LD and multi above the FX6's blocks"] = excl and not any(x["fits"] for x in excl)
    checks["the FX6 codec firmware's getters are the A7 IV's instructions (+0x18) and its calculation starts as the A7 IV's"] = all(res["getters"].values())
    checks["self-check: every stock QFHD XAVC-L / XAVC-I descriptor's codec need fits the FX6's 4K blocks"] = all(x["fits"] for x in selfchk)
    checks["each changed descriptor's codec need at 3840x2560 fits the FX6's 4K blocks (CD 0x486, LD 0x474, multi 0x477), no firmware assert"] = all(x["fits"] for x in fits)

    # ---- start-block builder
    prof = {}
    for base, cnt in B6.PROFILES:
        for k in range(cnt):
            prof[struct.unpack_from("<I", av, base + k * 0x100 + 0x20)[0]] = base + k * 0x100
    starts, sgood = [], True
    for p in design["descriptors"]:
        d = s.desc(p["descriptor"])
        o = prof[d["key"]]
        try:
            a, seq_a = s.start_block(av[o:o + 0x100], d, W0, H0, p["family"] == "xi" or "10-bit" in p["format"])
            b, seq_b = c.start_block(av2[o:o + 0x100], d, W1, H1, p["family"] == "xi" or "10-bit" in p["format"])
        except RuntimeError as ex:
            starts.append({"descriptor": p["descriptor"], "error": str(ex)})
            sgood = False
            continue
        f0, f1 = struct.unpack_from("<H", seq_a, 0xC)[0], struct.unpack_from("<H", seq_b, 0xC)[0]
        ok = (a["returned"] == b["returned"] == 1 and not a["errors_logged"] and not b["errors_logged"] and a["crop_size"] == [W0, H0] and b["crop_size"] == [W1, H1])
        sgood &= ok
        starts.append({"descriptor": p["descriptor"], "stock_2160": a, "changed_2560": b, "seq_0xc": [f0, f1], "ok": ok})
    res["start_block"] = starts
    checks["start-block builder 0x20559c: stock profile at 3840x2160 and changed profile at 3840x2560 both accepted, crop = the picture"] = sgood

    # ---- clip-format code
    res["clip_code"] = {"stock_3840x2160": s.clip(W0, H0), "stock_3840x2560": s.clip(W1, H1), "changed_3840x2560": c.clip(W1, H1),
                        "changed_3840x2160": c.clip(W0, H0), "changed_8192x4320": c.clip(8192, 4320), "changed_4096x2160": c.clip(4096, 2160)}
    cc = res["clip_code"]
    checks["clip-format code of 3840x2560 is the 3840x2160 code 16 after the change (stock: none); 3840x2160 and 4096x2160 unchanged"] = (
        cc["stock_3840x2160"] == cc["changed_3840x2160"] == cc["changed_3840x2560"] == 16 and cc["stock_3840x2560"] == 0 and cc["changed_4096x2160"] == 14)

    res["checks"] = checks
    out = ROOT / "evidence" / "fx6" / "ogfile_fx6_emu.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1) + "\n", encoding="utf8", newline="\n")
    bad = 0
    for text, ok in checks.items():
        print("   %s  %s" % ("PASS" if ok else "FAIL", text))
        bad += not ok
    one = next(iter(mem.values()))
    print("   memory ids e.g.:", one["stock_2160"]["memory_ids_asked"], "->", one["changed_2560"]["memory_ids_asked"])
    print("   codec need at 2560:", [(x["descriptor"], x["need"]) for x in fits][:2], "blocks", have)
    print("   clip codes:", cc)
    if bad:
        raise SystemExit("%d check(s) failed" % bad)
    print("all checks passed; wrote", out)


if __name__ == "__main__":
    main()
