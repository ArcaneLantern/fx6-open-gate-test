# FX6 6.02 port: the LCD at 3:2 (screen step `lcd32_fx6_v1`)

Build `fx6_602` (ILME-FX6, firmware 6.02; `cpapp-b.bin` loaded at 0x108000, SHA-256 `b432af72…def6`). Written 2026-11-26 by the screen
part of the FX6 open-gate port. Static analysis and Unicorn emulation only: nothing here has run on an FX6.

- Builder: `build/build_lcd_fx6.py` → `modding/designs/lcd32_fx6_v1.json` (8 words, 30 guards).
- Emulation: `build/emu_lcd_fx6.py --save` → `evidence/fx6/lcd32_fx6_v1_emu.json` (43 cases, all as expected).
- Reference: the FX3's `lcd32dsq_fx3_v1` (`build/build_lcd_fx3.py`), whose screen step works on an FX3 (2026-11-24).

## What the FX6's display code is

The FX6's layout code is the FX3's family, compiled differently (only the layout function and the panel-type function match the FX3's
bytes; the fit, ratio and de-squeeze functions are other compiles). Found with `build/match_thumb.py`, `build/match_seed.py`, call-site scans
and disassembly:

| What | FX3 7.02 | FX6 6.02 | How found |
|---|---|---|---|
| automatic layout | 0x1df884 | **0x1db458** | match_thumb (72 bytes, 1 hit) |
| panel-type function | 0x1e0050 | **0x1dba9c** | match_thumb (40 bytes, 1 hit); same instructions |
| panel-type tables (devices 1/2; device 0x20) | 0x1e00f4 … | **0x1dbb40** [0xff, 1, 0, 2]; **0x1dbb34** [0xff, 1, 0] | read |
| panel-code table | 0xb7f034 | **0xce4ee8** [0, 2, 1, 0, 1, 2, 3, 4, 5, …] (from index 3 on the identity table 0xce4ef4) | read; only 0x1dbad8 builds 0xce4ee8 |
| rear panel-type byte | RAM 0x14909e4 | **RAM 0x1703944** (0x5f09e4: `[0x1703928 + 0x1c]`, ≥ 4 → 1) | disassembly |
| second output's type byte | RAM 0x1490b14 | **RAM 0x1703a74** (0x5f09f6, ≥ 2 → 2) | disassembly |
| panel-code getter | — | **0x60a91a** (devices 1, 2, 4, 0x20 → 0x1dba9c; 0x40 / 0x80 → 0x1db7f4, table 0x1db810 [2, 0, 2, 2, 5, 2, 5]; others 2) | disassembly |
| fit mode | 0x1df458 (tables 0x1df4a8 …) | **0x1db108** (tables 0x1db154 / 0x1db16c / 0x1db184) | match_seed (58 votes) + disassembly |
| picture ratio | 0x1df794 (16:9 case 0x1df7b8) | **0x1db32c** (16:9 case 0x1db34e / 0x1db350) | layout's call 0x1db6ac |
| de-squeeze active | 0x60eb6e | **0x625e28** | layout's call 0x1db67e |
| de-squeeze calculator | 0x1df680 | **0x60b2ec** | layout's call 0x1db698 |
| 2.0x input crop | 0x5faf04 (compares 0x5faf36 / 0x5faf68) | **0x60cf1e** (one compare, 0x60cf42) | match_seed (14 votes) + disassembly |
| VdfInputCmdSetDeSqueeze check | 0x5f5442 (code < 5) | **0x606e46** (code ≤ 4 and ≠ 3) | `movw r1, #0x1327` search |
| imaging de-squeeze scale store (SET_ANAMO_DESQUEEZE_SCALE) | RAM 0x10a8eb4 | **RAM 0x12c0408** (`0x12c0338 + 0xd0`, handler before the string 0x301c3d) | disassembly |
| second layout (another plane of a device) | — | **0x60af6e** (callers 0x60ac16, 0x60b430, 0x60b4c4) | callers of 0x60a91a |
| HDMI rectangle (device 4) | — | **0x60c9a8** | callers of 0x60a91a |
| display timing table | 0xd7231c | 0xecf1f2: **byte-identical to the FX3's for 0x1a14 bytes** | match_seed + compare |
| frame-widget tables / frame check | 0xd2e510 / 0xd2e588 / 0xd2e600; 0x128438 | **none**: no `cpActAfWindowRemoteSend`, no 640.0 / 480.0 doubles, no `vmov.f64 d1, #5.0` | byte searches |

## Panel facts

- **Observed in the firmware:** the panel shape is a run-time byte (rear: RAM 0x1703944) mapped to a panel code: type 1 → code 2 (16:9),
  type 2 → code 0 (4:3), type 3 → code 1 (3:2), type 0 → code 0. The FX6 has the FX3's panel-type logic unchanged.
- **Not settled by the firmware:** which type the FX6's LCD reports. The display timing table is the FX3's byte for byte (it lists 640 × 480,
  800 × 600, 960 × 540, 1280 × 720, … geometries for every body), so it does not name the FX6's panel. Sony gives the FX6 LCD as a 3.5-type
  2.76M-dot 16:9 panel (= 1280 × 720 × 3), so **type 1 (16:9) is expected**. The design is right for types 1, 2 and 3; the dump reads the byte.
- The device ids are the FX3's: 1 = rear output, 2 = a second output, 4 = HDMI, 0x20 and 0x40 / 0x80 others (SDI is probably one of the
  latter: not traced).

## Why the FX3's fix is not enough on a 16:9 panel

The fit function 0x1db108 returns 0 (fill the panel) whenever panel code == picture code, before it reads any table. The open-gate live view
is a 16:9 picture (code 2) and a 16:9 panel is code 2, so on the FX6 the ratio function is never asked and the FX3's 9/16 → 2/3 change alone
would show nothing. The fit tables (read from the image, emulated for all 36 pairs):

| picture → / panel code ↓ | 4:3 (0) | 3:2 (1) | 16:9 (2) | 17:9 (5) |
|---|---|---|---|---|
| 0 (4:3) | 0 | 3 | 3 | 3 |
| 1 (3:2) | 2 | 0 | 3 | 3 |
| 2 (16:9) | 2 | 2 | **0** | 3 |
| 5 (17:9) | 2 | 2 | **2** | **0** |

Fit 3 = letterbox (height = width × n/d), fit 2 = **pillarbox** (width = height × d/n, centred: ratio function 0x1db364). Only panel code 5
pillarboxes a 16:9 picture.

## The design `lcd32_fx6_v1` (8 RAM words of the coprocessor image)

| Word | Stock → new | What |
|---|---|---|
| 0x1dbb44 | 1 → 8 | panel-type table 0x1dbb40 (devices 1 and 2), type 1: index 1 (code 2) → index 8 (code 5). Code 5 differs from code 2 only in the fit of a 16:9 picture (0 → 2) and of a 17:9 picture (3 → 0). Alone it shows nothing new: a 16:9 pillarbox of a 16:9 picture is the whole panel |
| 0x1db34c | `movs r0, #9` → `#2` (at 0x1db34e) | picture ratio, 16:9 picture: numerator |
| 0x1db350 | `movs r2, #0x10` → `#3` | picture ratio, 16:9 picture: denominator. 9/16 → 2/3, the function's own 3:2 case (0x1db348). On 1280 × 720: (100, 0, 1080, 720) |
| 0x60b354 | `mov.w sl, #3` → `#1` | de-squeeze code 4 (2.0x, every picture shape) and code 2 with a 16:9 picture |
| 0x60b358 | `movs r6, #8` → `#3` | 3/8 → 1/3: the whole 3:2 frame at 3:1 (the owner's FX3 choice) |
| 0x60b35c | `mov.w sl, #0x2d` → `#0x14` | de-squeeze code 1 (1.3x), 16:9 picture |
| 0x60b360 | `movs r6, #0x68` → `#0x27` | 45/104 → 20/39: 1.95:1 |
| 0x60cf40 | `cmp r0, #4` → `#5` (at 0x60cf42) | 2.0x centre crop off: 0x606e46 refuses codes 3 and > 4, so 5 is never stored (emulated) |

30 guards (each 4-aligned, ≤ 16 bytes, none overlapping a site): the fit function's early-out and its three tables, the ratio function
(start, case table and 3:2 case, the 17:9 case and fit dispatch, the pillarbox), the panel-type function's device tests and table lookups,
the tables 0x1dbb34 / 0x1dbb40 (the other entries) and 0xce4ee8 (indices 0–8: index 8 = 5), the panel-code getter, the layout's fit call,
the de-squeeze calculator (code read and switch, the 17:9 ratios left alone, the height calculation), the crop function (de-squeeze test,
code read, device test, the 4:3 crop) and the VDF command's code check.

For a write helper's region list (as gen_fx3_write.py's `WORD_REGIONS`): sites lie in (0x1db34c, 0x1db354), (0x1dbb44, 0x1dbb48),
(0x60b354, 0x60b364), (0x60cf40, 0x60cf44); guards also in (0x1db108, 0x1db198), (0x1db32c, 0x1db374), (0x1db664, 0x1db670),
(0x1dbaa0, 0x1dbb50), (0xce4ee8, 0xce4f0c), (0x60a91c, 0x60a92c), (0x60b2f0, 0x60b374), (0x60cf20, 0x60cf90), (0x606e48, 0x606e58).

### The De-Squeeze Display

- **Observed:** appFw 6.02 offers `EXTERN_VAL_DE_SQUEEZE_DISP_OFF_1_0X`, `_1_3X`, `_2_0X` (no 1.5x / 1.65x / 1.8x). The coprocessor accepts
  VDF codes 0, 1, 2, 4 (0x606e46). The calculator: code 1 = 1.3x (16:9 45/104, 17:9 675/1664), code 2 = 1.5x (16:9 3/8, 17:9 45/128),
  code 4 = 2.0x (3/8 for every shape, after the crop function cuts a centre 4:3).
- **Inferred, not read:** the menu's 1.3x and 2.0x send codes 1 and 4 (the FX3/A7S III family's codes). appFw's BB path
  (`video_set_de_squeeze_disp` 0x20f78f4) maps settings 1, 2, 5 → 1, 2, 3 and its imaging path (`set_de_squeeze_disp_i` 0x2112fbc) 1, 2, 5 →
  1, 3, 2; neither is the VDF code itself. Whatever code 2.0x sends (2 or 4), the design shows the 3:2 frame at 3:1. If code 2 were ever
  1.5x, it would show 3:1 instead of 2.25:1 (code 2's 16:9 case shares code 4's instructions).

## Emulation (Unicorn, the FX6's own code; `evidence/fx6/lcd32_fx6_v1_emu.json`)

- **Panel codes:** rear type 0/1/2/3 → stock 0/2/0/1, patched 0/**5**/0/1; device 2 type 1 → 2 / **5**; device 0x20, device 4 (HDMI;
  slot 0x658 = 0, 5, 0xa) and devices 0x40 / 0x80 (slot 0x718 = 0–6): unchanged.
- **Fit:** all 36 (panel, picture) pairs equal stock (the function is not changed).
- **Whole layout 0x1db458, LCD (device 1), de-squeeze off, 16:9 picture (the open-gate frame):**

  | Panel (type) | Stock | Patched | Shown |
  |---|---|---|---|
  | 1280 × 720 (1) | (0, 0, 1280, 720) | **(100, 0, 1080, 720)** | 1.500 |
  | 960 × 540 (1) | (0, 0, 960, 540) | **(76, 0, 808, 540)** | 1.496 |
  | 800 × 600 (2) | (0, 75, 800, 450) | (0, 33, 800, 534) | 1.498 (= the FX3's numbers) |
  | 720 × 480 (3) | (0, 38, 720, 404) | (0, 0, 720, 480) | 1.500 |

  4:3 and 3:2 pictures: unchanged on every panel. 17:9 picture on a 16:9 panel: stock letterbox (0, 23, 1280, 674), patched fills (side effect).
- **Second layout 0x60af6e** (device 1, 1280 × 720): a plane with picture code 2 gets the same (100, 0, 1080, 720); 4:3 and 3:2 unchanged.
- **HDMI (device 4):** a 16:9 output (code 2) is unchanged (0, 0, 1920, 1080). A 4096-wide output (code 5) pillarboxes at 3:2 instead of 16:9.
  The 0x40 outputs: the same (slot 0x718 = 4 or 6 → code 5: (300, 0, 3240, 2160) of 3840 × 2160 instead of the whole).
- **De-squeeze on, LCD 1280 × 720:** code 1: stock (0, 84, 1280, 552) → (0, 32, 1280, 656) = 1.951:1 (1.95 wanted); codes 2 and 4: stock
  (0, 120, 1280, 480) → (0, 146, 1280, 428) = 2.991:1 (3:1 wanted). 17:9, 4:3, 3:2 pictures with codes 1 / 2: unchanged; code 4: 1/3 for every shape.
- **2.0x crop:** stock crops 1920 → 1440 at x 240 on both paths (any device; device 4 with slot 0x658 = 8); patched leaves the whole frame.
  Codes 1 and 2: no crop, stock and patched.
- **VDF check 0x606e46:** codes 0, 1, 2, 4 accepted; 3, 5, 6 refused (stock = patched).

Not done: the qemu-arm cross-check the FX3 had (`build/lcd_fx3_qemu.py`). Unicorn ran the FX6's whole layout function here, not only its leaves.

## While the step is applied

- Every 16:9 picture on the LCD is shown at 3:2 with black bars left and right (open-gate live view: right; ordinary 16:9 recording or playback: squeezed).
- A 17:9 (DCI) picture fills the LCD, 6% taller than true (stock letterboxes it). Put the step back for DCI.
- The de-squeeze ratios are a 3:2 picture's on every output that de-squeezes (the calculator is shared; HDMI de-squeeze too); 2.0x shows any picture at 3:1.
- HDMI and the 0x40 / 0x80 outputs keep their panel codes: a 16:9 output shows the stock squeezed 16:9 frame; a 4096-wide output
  pillarboxes at 3:2 instead of 16:9.

## Read-only dump pages (as gen_fx3.py's `DUMP_RANGES`)

| Name | Address | Pages | Holds |
|---|---|---|---|
| display | 0x1db000 | 1 | fit 0x1db108 + tables, ratio 0x1db32c (sites 0x1db34c / 0x1db350), layout 0x1db458, panel-type 0x1dba9c, table 0x1dbb40 (site 0x1dbb44) |
| dsqcalc | 0x60b000 | 1 | de-squeeze calculator, sites 0x60b354–0x60b360 |
| crop | 0x60c000 | 1 | crop function, site 0x60cf40 |
| paneltype | 0x1703000 | 1 | panel records 0x1703928 / 0x1703a58: rear type byte 0x1703944, second 0x1703a74 |
| desqueeze | 0x12c0000 | 1 | the imaging de-squeeze scale 0x12c0408 (SET_ANAMO_DESQUEEZE_SCALE) |
| panelcode (optional) | 0xce4000 | 1 | constant table 0xce4ee8 (guarded; never changes) |

The VDF de-squeeze code byte itself lives in a device object reached through slot 0x708: not at a fixed address.

## Risks and unknowns

- Nothing has run on an FX6. The FX3's screen step (code words in the same kind of pages, written in RAM) works on the FX3.
- **Inferred:** the FX6 LCD reports panel type 1 (16:9) and is device 1. If it reports 2 or 3, the design still gives 3:2 (letterbox; emulated).
  If it were another device id or type 0, the LCD would stay as stock.
- **Inferred:** the menu's 1.3x / 2.0x send VDF codes 1 / 4.
- **Unknown:** how the FX6 draws focus frames, the OSD and the safety/frame markers. It has no FX3-style frame check. The second layout lays a
  plane with picture code 2 out at the same 3:2 box; which planes have which code is set at run time (slot 0x3f0). If the focus-frame plane
  keeps the full 16:9 box, frames are drawn as if the picture were full width (horizontally off by up to 100 px at the edges).
- **Unknown:** whether the panel code is cached anywhere after start-up (0x60a91a recomputes it on every layout call; a layout must run after
  the write, e.g. a mode change or menu, as on the FX3).
- HDMI / SDI at a 4096-wide output resolution pillarbox the 16:9 picture at 3:2 while applied (emulated); a 16:9 output is unchanged.
