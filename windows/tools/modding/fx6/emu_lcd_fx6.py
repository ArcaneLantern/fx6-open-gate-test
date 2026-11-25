"""Emulate the FX6 6.02 display layout, stock and with lcd32_fx6_v1 applied, in Unicorn on the FX6's own code.

  C:\\Python313\\python.exe -B build\\emu_lcd_fx6.py [--save]      (--save writes evidence/fx6/lcd32_fx6_v1_emu.json)

Functions run (cpapp-b.bin 6.02, loaded at 0x108000):
  0x60a91a  panel code (device, object): devices 1/2/4/0x20 -> 0x1dba9c (rear type byte RAM 0x1703944, second 0x1703a74; device 4 and
            0x20 ask the object: slots 0x658 / 0x66c / 0x670 / 0x854), 0x40/0x80 -> 0x1db7f4 (slot 0x718)
  0x1db108  fit mode (panel code, picture code)
  0x1db32c  picture ratio: (_, w | h << 16, panel, picture, [fit, out]) -> out = x, y, w, h
  0x60b2ec  de-squeeze calculator: (_, w | h << 16, panel, picture, [fit, out, object, device]); code bytes from slot 0x708, slot 0x658 (device 4)
  0x60cf1e  2.0x input crop: (rect, _, object, device); 0x625e28 (de-squeeze active) stubbed -> 1
  0x606e46  VdfInputCmdSetDeSqueeze's check (command object slot 8 -> the code bytes; 0x74 accept, 0x88 refuse)
  0x1db458  the whole layout, automatic path (every helper it calls through the device object is a stub; 0x60a890 gives the output size,
            0x625ae6 / 0x625afe give the sizes that select the automatic path, 0x625e28 de-squeeze on/off, 0x625b0e / 0x625b2e margins 0);
            the rectangle it hands to slot 0x42c is what the output shows
  0x60af6e  the second layout (another plane of the device), the same way (picture code from slot 0x3f0)
Panels: 1280 x 720 and 960 x 540 (16:9, type 1: the FX6's LCD is 16:9), 800 x 600 (4:3, type 2) and 720 x 480 (3:2, type 3), so the step
is checked whatever type the FX6 reports. Every expected value is asserted. Read-only apart from the evidence file.
"""
import json
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_UNMAPPED
from unicorn import arm_const as A

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import locate_file  # noqa: E402

B = 0x108000
FX = locate_file.locate("fx6_602", "cpapp-b.bin").read_bytes()
DESIGN = json.loads((ROOT / "modding/designs/lcd32_fx6_v1.json").read_text(encoding="utf8"))
RET, STK, OBJ, STUBS, SCR = 0x2410000, 0x2300000, 0x2440000, 0x2480000, 0x2400000
REAR_TYPE, SECOND_TYPE = 0x1703944, 0x1703A74
PANELS = {"16:9 1280x720": (1280, 720, 1), "16:9 960x540": (960, 540, 1), "4:3 800x600": (800, 600, 2), "3:2 720x480": (720, 480, 3)}
KIND = {0: 0, 1: 2, 2: 1, 6: 5}                                       # the layout's picture kind (slot 0x430) -> picture code (0x1db640)
PIC = {0: "4:3", 1: "3:2", 2: "16:9", 5: "17:9"}


class Cp:
    def __init__(self, patched):
        img = bytearray(FX)
        if patched:
            for s in DESIGN["sites"]:
                a = int(s["ram_address"], 16)
                assert img[a - B:a - B + 4] == bytes.fromhex(s["old"])
                img[a - B:a - B + 4] = bytes.fromhex(s["new"])
            for g in DESIGN["guards"]:
                a = int(g["ram_address"], 16)
                assert img[a - B:a - B + len(g["bytes"]) // 2] == bytes.fromhex(g["bytes"])
        self.uc = uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        try:
            uc.ctl_set_cpu_model(A.UC_CPU_ARM_CORTEX_A15)
        except Exception:
            pass
        uc.mem_map(0x100000, 0x2500000)
        uc.mem_write(B, bytes(img))
        uc.reg_write(A.UC_ARM_REG_C1_C0_2, uc.reg_read(A.UC_ARM_REG_C1_C0_2) | (0xF << 20))
        uc.reg_write(A.UC_ARM_REG_FPEXC, 0x40000000)
        self.stubs, self.log, self.slots, self.calls = {}, [], {}, []
        uc.hook_add(UC_HOOK_MEM_UNMAPPED, lambda u, acc, addr, sz, v, _: self.log.append(f"unmapped {addr:#x} pc={u.reg_read(A.UC_ARM_REG_PC):#x}") or False)
        # the device object: [OBJ] = vtable; every slot points to its own stub (bx lr), dispatched by self.slots (default: return 0)
        vt = OBJ + 0x1000
        uc.mem_write(OBJ, struct.pack("<I", vt))
        for slot in range(0, 0x1000, 4):
            a = STUBS + slot
            uc.mem_write(a, b"\x70\x47")
            uc.mem_write(vt + slot, struct.pack("<I", a | 1))
        uc.hook_add(UC_HOOK_CODE, lambda u, ad, sz, _: self._slot(ad), begin=STUBS, end=STUBS + 0x1000)
        self.code_ptr = OBJ + 0x3000

    # ---- stubs
    def _slot(self, addr):
        u, slot = self.uc, addr - STUBS
        fn = self.slots.get(slot)
        self.calls.append(slot)
        r0 = fn(u) if fn else 0
        if slot == 0x610:                                               # a 64-bit result (r0, r1): 0 = no configuration block
            u.reg_write(A.UC_ARM_REG_R1, 0)
        u.reg_write(A.UC_ARM_REG_R0, (r0 or 0) & 0xFFFFFFFF)
        u.reg_write(A.UC_ARM_REG_PC, u.reg_read(A.UC_ARM_REG_LR))

    def stub(self, addr, fn):
        if addr not in self.stubs:
            self.uc.hook_add(UC_HOOK_CODE, lambda u, ad, sz, _: self._run_stub(ad), begin=addr, end=addr)
        self.stubs[addr] = fn

    def _run_stub(self, addr):
        u = self.uc
        r0 = self.stubs[addr](u)
        if r0 is not None:
            u.reg_write(A.UC_ARM_REG_R0, r0 & 0xFFFFFFFF)
        u.reg_write(A.UC_ARM_REG_PC, u.reg_read(A.UC_ARM_REG_LR))

    def call(self, fn, regs, stack=()):
        u = self.uc
        sp = STK - 0x800
        for i, v in enumerate(stack):
            u.mem_write(sp + 4 * i, struct.pack("<I", v & 0xFFFFFFFF))
        for r, v in zip((A.UC_ARM_REG_R0, A.UC_ARM_REG_R1, A.UC_ARM_REG_R2, A.UC_ARM_REG_R3), regs):
            u.reg_write(r, v & 0xFFFFFFFF)
        u.reg_write(A.UC_ARM_REG_SP, sp)
        u.reg_write(A.UC_ARM_REG_LR, RET | 1)
        u.emu_start(fn | 1, RET, count=200000)
        assert not self.log, self.log
        return u.reg_read(A.UC_ARM_REG_R0)

    def rect(self, a):
        return list(struct.unpack("<4H", bytes(self.uc.mem_read(a, 8))))

    def set_type(self, rear=None, second=None):
        if rear is not None:
            self.uc.mem_write(REAR_TYPE, bytes([rear]))
        if second is not None:
            self.uc.mem_write(SECOND_TYPE, bytes([second]))

    def set_code(self, code, enable=1):
        self.uc.mem_write(self.code_ptr, bytes([code, enable, 0, 0]))
        self.slots[0x708] = lambda u: self.code_ptr

    # ---- leaf functions
    def panel_code(self, device):
        return self.call(0x60A91A, (device, OBJ))

    def fit(self, panel, pic):
        return self.call(0x1DB108, (panel, pic))

    def ratio(self, w, h, panel, pic):
        out = SCR
        self.uc.mem_write(out, bytes(8))
        self.call(0x1DB32C, (0, w | h << 16, panel, pic), (self.fit(panel, pic), out))
        return self.rect(out)

    def desqueeze(self, w, h, panel, pic, code, device=1):
        out = SCR
        self.uc.mem_write(out, bytes(8))
        self.set_code(code)
        self.call(0x60B2EC, (0, w | h << 16, panel, pic), (self.fit(panel, pic), out, OBJ, device))
        return self.rect(out)

    def crop(self, code, device=1, full_w=1920, h=1080, slot658=0):
        r = SCR + 0x100
        self.uc.mem_write(r, bytes(0x40))
        self.uc.mem_write(r + 8, struct.pack("<H", full_w))
        self.uc.mem_write(r + 0xC, struct.pack("<HHHH", 0, 0, full_w, h))
        self.set_code(code)
        self.slots[0x658] = lambda u: slot658
        self.stub(0x625E28, lambda uc: 1)
        self.call(0x60CF1E, (r, 0, OBJ, device))
        x_, _, w_, h_ = struct.unpack("<4H", bytes(self.uc.mem_read(r + 0xC, 8)))
        return [x_, w_, h_]

    def vdf_check(self, code, enable=1):
        cmd = OBJ + 0x5000
        vt = OBJ + 0x6000
        u = self.uc
        u.mem_write(cmd, struct.pack("<I", vt))
        data = OBJ + 0x7000
        u.mem_write(data, bytes([code, enable, 0, 0]))
        res = {}
        for slot, fn in ((8, lambda uc: data), (0x74, lambda uc: res.setdefault("accepted", 1) and 0), (0x88, lambda uc: res.setdefault("refused", 1) and 0)):
            a = STUBS + 0x800 + slot
            u.mem_write(vt + slot, struct.pack("<I", (STUBS + slot) | 1))
        saved = dict(self.slots)
        self.slots[8] = lambda uc: data
        self.slots[0x74] = lambda uc: res.setdefault("accepted", 1) and 0
        self.slots[0x88] = lambda uc: res.setdefault("refused", 1) and 0
        r0 = self.call(0x606E46, (0, cmd))
        self.slots = saved
        return r0, res

    # ---- the whole layout, automatic path
    def layout(self, fn, device, w, h, kind=1, dsq=0, code=0, slot3f0=2, slot658=0, slot718=0):
        u = self.uc
        self.slots = {}
        got = {}
        self.slots[0x430] = lambda uc: kind
        self.slots[0x3F0] = lambda uc: slot3f0
        self.slots[0x658] = lambda uc: slot658
        self.slots[0x718] = lambda uc: slot718

        def set_rect(uc):
            got["rect"] = list(struct.unpack("<4H", bytes(uc.mem_read(uc.reg_read(A.UC_ARM_REG_R1), 8))))
            return 0
        self.slots[0x42C] = set_rect
        self.set_code(code)

        def out_size(uc):
            r0 = uc.reg_read(A.UC_ARM_REG_R0)
            uc.mem_write(r0, struct.pack("<4H", 0, 0, w, h))
            return None
        self.stub(0x60A890, out_size)
        for a in (0x625AE6, 0x625AFE, 0x625B0E, 0x625B2E, 0x625B8A, 0x625C0C, 0x625EA8):
            self.stub(a, lambda uc: 0)
        self.stub(0x625E28, lambda uc: dsq)
        if fn == 0x1DB458:
            st = SCR + 0x200
            u.mem_write(st, bytes(0x20))                                    # every size 0: the automatic path (0x1db4dc-0x1db512)
            self.call(0x1DB458, (0, device, OBJ, st))
        else:
            self.call(0x60AF6E, (0, device, OBJ))
        return got.get("rect")


def run():
    st, pa = Cp(False), Cp(True)
    res = {"design": DESIGN["design"], "image_sha256": DESIGN["artifact_sha256"], "cases": []}
    case = lambda **k: res["cases"].append(k)
    both = lambda f: (f(st), f(pa))
    # ---- panel codes
    want = {0: (0, 0), 1: (2, 5), 2: (0, 0), 3: (1, 1)}                 # rear type byte -> (stock, patched) panel code
    for t, (s_w, p_w) in want.items():
        st.set_type(rear=t), pa.set_type(rear=t)
        s, p = st.panel_code(1), pa.panel_code(1)
        assert (s, p) == (s_w, p_w), (t, s, p)
        case(what="panel code, device 1 (rear), type byte %d" % t, stock=s, patched=p)
    for t, (s_w, p_w) in {0: (0, 0), 1: (2, 5), 2: (0, 0)}.items():
        st.set_type(second=t), pa.set_type(second=t)
        s, p = st.panel_code(2), pa.panel_code(2)
        assert (s, p) == (s_w, p_w), (t, s, p)
        case(what="panel code, device 2, type byte %d" % t, stock=s, patched=p)
    for v in range(0, 3):                                               # device 0x20: its own table 0x1dbb34
        for cp in (st, pa):
            cp.slots = {0x854: (lambda vv: lambda uc: vv)(v)}
        s, p = st.panel_code(0x20), pa.panel_code(0x20)
        assert s == p, (v, s, p)
        case(what="panel code, device 0x20, index %d" % v, stock=s, patched=p)
    for v, wnt in ((0, 2), (0xA, 5), (5, 2)):                           # device 4 (HDMI): computed, no table
        for cp in (st, pa):
            cp.slots = {0x658: (lambda vv: lambda uc: vv)(v)}
        s, p = st.panel_code(4), pa.panel_code(4)
        assert s == p == wnt, (v, s, p)
        case(what="panel code, device 4 (HDMI), slot 0x658 = %#x" % v, stock=s, patched=p)
    for v in range(0, 7):                                               # devices 0x40 / 0x80: table 0x1db810
        for cp in (st, pa):
            cp.slots = {0x718: (lambda vv: lambda uc: vv)(v)}
        s, p = st.panel_code(0x40), pa.panel_code(0x40)
        assert s == p, (v, s, p)
    case(what="panel code, devices 0x40 / 0x80, slot 0x718 = 0..6", stock_equals_patched=True)
    # ---- fit: the function is not changed; the pillarbox comes from panel code 5
    table = {}
    for panel in range(6):
        for pic in range(6):
            s, p = st.fit(panel, pic), pa.fit(panel, pic)
            assert s == p
            table[f"{panel},{pic}"] = s
    assert table["2,2"] == 0 and table["5,2"] == 2 and table["0,2"] == table["1,2"] == 3 and table["2,5"] == 3 and table["5,5"] == 0
    case(what="fit mode (panel code, picture code), all 36 pairs", stock_equals_patched=True, fit=table)
    # ---- the picture ratio alone, every panel shape and picture
    for name, (w, h, t) in PANELS.items():
        for pic in (0, 1, 2, 5):
            for panel in (0, 1, 2, 5):
                s, p = st.ratio(w, h, panel, pic), pa.ratio(w, h, panel, pic)
                if pic != 2:
                    assert s == p, (name, panel, pic)
        case(what="picture ratio, pictures 4:3 / 3:2 / 17:9 on panel codes 0, 1, 2, 5", panel=name, stock_equals_patched=True)
    # ---- the whole layout, device 1 (the LCD), every picture kind, de-squeeze off
    exp = {"16:9 1280x720": {2: ([0, 0, 1280, 720], [100, 0, 1080, 720])}, "16:9 960x540": {2: ([0, 0, 960, 540], [76, 0, 808, 540])},
           "4:3 800x600": {2: ([0, 75, 800, 450], [0, 33, 800, 534])}, "3:2 720x480": {2: ([0, 38, 720, 404], [0, 0, 720, 480])}}   # = the FX3's
    for name, (w, h, t) in PANELS.items():
        st.set_type(rear=t), pa.set_type(rear=t)
        for kind, pic in KIND.items():
            s = st.layout(0x1DB458, 1, w, h, kind)
            p = pa.layout(0x1DB458, 1, w, h, kind)
            if pic == 2:
                assert [s, p] == list(exp[name][2]), (name, s, p)
                shown = p[2] / p[3]
                assert abs(shown - 1.5) < 0.01, shown
                case(what="LCD layout (device 1), 16:9 picture = the open-gate frame, de-squeeze off", panel=name, type_byte=t, stock=s, patched=p,
                     shown_aspect=round(shown, 4))
            elif pic == 5 and t == 1:                                    # 17:9 on the 16:9 panel: letterbox -> fill (the known side effect)
                assert s[2] == w and s[3] < h and p == [0, 0, w, h], (name, s, p)
                case(what="LCD layout (device 1), 17:9 (DCI) picture on the 16:9 panel", panel=name, stock=s, patched=p,
                     note="side effect: fills the panel while the step is applied")
            else:
                assert s == p, (name, pic, s, p)
        case(what="LCD layout (device 1), 4:3 and 3:2 pictures (and 17:9 on the 4:3 / 3:2 panels)", panel=name, stock_equals_patched=True)
    # ---- the second layout (another plane of the device), device 1, picture code from slot 0x3f0
    st.set_type(rear=1), pa.set_type(rear=1)
    for pic in (0, 1, 2, 5):
        s = st.layout(0x60AF6E, 1, 1280, 720, slot3f0=pic)
        p = pa.layout(0x60AF6E, 1, 1280, 720, slot3f0=pic)
        if pic == 2:
            assert s == [0, 0, 1280, 720] and p == [100, 0, 1080, 720], (s, p)
        elif pic == 5:
            assert p == [0, 0, 1280, 720] and s != p, (s, p)
        else:
            assert s == p, (pic, s, p)
        case(what="second layout 0x60af6e (another plane), device 1, 1280x720, picture %s" % PIC[pic], stock=s, patched=p)
    # ---- HDMI (device 4) and the 0x40 output: whole layout
    for v, nm in ((0, "16:9 output (code 2)"), (0xA, "4096-wide output (code 5)")):
        s = st.layout(0x1DB458, 4, 1920, 1080, 1, slot658=v)
        p = pa.layout(0x1DB458, 4, 1920, 1080, 1, slot658=v)
        if v == 0:
            assert s == p == [0, 0, 1920, 1080], (s, p)
        else:
            assert s == [0, 0, 1920, 1080] and p == [150, 0, 1620, 1080], (s, p)
        case(what="HDMI layout (device 4), 16:9 picture, " + nm, stock=s, patched=p)
    for v in range(7):
        s = st.layout(0x1DB458, 0x40, 3840, 2160, 1, slot718=v)
        p = pa.layout(0x1DB458, 0x40, 3840, 2160, 1, slot718=v)
        code = [2, 0, 2, 2, 5, 2, 5][v]
        if code == 5:
            assert s == [0, 0, 3840, 2160] and p == [300, 0, 3240, 2160], (v, s, p)
        else:
            assert s == p == [0, 0, 3840, 2160], (v, s, p)
    case(what="output 0x40 layout, 16:9 picture, slot 0x718 = 0..6", note="codes 2 / 0: unchanged; slot 4 and 6 (code 5, a 4096-wide output): pillarbox 3:2 instead of the whole")
    # ---- de-squeeze (LCD, 1280 x 720, type 1): codes 1, 2, 4
    st.set_type(rear=1), pa.set_type(rear=1)
    fac = {1: 1.3, 2: 1.5, 4: 2.0}
    want_p = {1: [0, 32, 1280, 656], 2: [0, 146, 1280, 428], 4: [0, 146, 1280, 428]}
    want_s = {1: [0, 84, 1280, 552], 2: [0, 120, 1280, 480], 4: [0, 120, 1280, 480]}
    for code in (1, 2, 4):
        s = st.layout(0x1DB458, 1, 1280, 720, 1, dsq=1, code=code)
        p = pa.layout(0x1DB458, 1, 1280, 720, 1, dsq=1, code=code)
        assert s == want_s[code] and p == want_p[code], (code, s, p)
        target = 1.5 * (2.0 if code != 1 else 1.3)
        assert abs(p[2] / p[3] / target - 1) < 0.012, (code, p, target)
        case(what=f"LCD layout with de-squeeze code {code} ({fac[code]}x per the calculator), 16:9 picture", stock=s, patched=p,
             shown_patched=round(p[2] / p[3], 4), right_for_the_3_2_frame_at_1_3x_or_2_0x=round(target, 4))
        for pic in (5, 0, 1):
            a_s = st.desqueeze(1280, 720, 5, pic, code)
            a_p = pa.desqueeze(1280, 720, 5, pic, code)
            if code != 4 and not (code == 2 and pic == 2):
                assert a_s == a_p, (code, pic, a_s, a_p)
            else:
                assert a_p[3] == ((1280 + 6) // 3) & ~3, (code, pic, a_p)
    case(what="de-squeeze 1.3x / 1.5x of 17:9, 4:3 and 3:2 pictures", stock_equals_patched=True, note="code 4's ratio serves every picture shape: 3/8 -> 1/3 for all")
    for code in (0, 3):
        assert st.desqueeze(1280, 720, 5, 2, code) == pa.desqueeze(1280, 720, 5, 2, code) == [0, 0, 1280, 720]
    # ---- 2.0x input crop
    for dev, s658, nm in ((1, 0, "path B (any device)"), (4, 8, "path A (device 4, slot 0x658 = 8)")):
        s, p = st.crop(4, dev, slot658=s658), pa.crop(4, dev, slot658=s658)
        assert s != [0, 1920, 1080] and p == [0, 1920, 1080], (nm, s, p)
        case(what="2.0x input crop, 1920 x 1080, " + nm, stock=s, patched=p)
        for code in (1, 2):
            assert st.crop(code, dev, slot658=s658) == pa.crop(code, dev, slot658=s658) == [0, 1920, 1080]
    # ---- the VDF command's check: 5 is never stored
    acc = {}
    for code in range(7):
        s, p = st.vdf_check(code), pa.vdf_check(code)
        assert s == p
        acc[code] = "accepted" if s[0] == 0 else "refused"
    assert acc == {0: "accepted", 1: "accepted", 2: "accepted", 3: "refused", 4: "accepted", 5: "refused", 6: "refused"}, acc
    case(what="VdfInputCmdSetDeSqueeze check 0x606e46, codes 0-6", result=acc)
    return res


if __name__ == "__main__":
    r = run()
    for c in r["cases"]:
        print(json.dumps(c))
    print(f"{len(r['cases'])} cases as expected")
    if "--save" in sys.argv:
        out = ROOT / "evidence" / "fx6" / "lcd32_fx6_v1_emu.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(r, indent=1) + "\n", encoding="utf8", newline="\n")
        print("wrote", out)
