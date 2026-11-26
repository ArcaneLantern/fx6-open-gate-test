# Port notes: FX3 7.02 kit → FX6 6.02

Everything here was read from the FX6 6.02 firmware update (`BODYDATA.DAT`, SHA-256 `dbb814d5…c339`). Every step was emulated: Unicorn ran the FX6's own code where it mattered, and the built helper libraries ran against a model FX6. The reference is the FX3 kit, which works on two FX3s (2026-11-24: true 3840 × 2560 in XAVC HS 4K and XAVC S 4K at 23.98p, the whole sensor area, the rear screen at 3:2). **Two FX6s have now run the steps** (issues 1 and 2); what they showed is in the next section.

Observed = read in the firmware or seen in emulation. Inferred = a reading of what was observed, not shown on a camera. "On a camera" = seen by a tester.

## What the first FX6 runs showed (2026-11-25 and 26)

| | Tester 1 (issue 1, macOS, XAVC-L 4:2:0 8-bit) | Tester 2 (issue 2, XAVC-I) |
|---|---|---|
| Sensor step alone | sensor on register column 1, drive mode 0x8c0; clips written (full height squeezed into 3840 × 2160; one take with a black band of about 210 rows at the top, a later one clean), then **`E95-311` after about 10 s of recording** | picture black, `E95-311`, beeps, blinking lamp; the picture came back after the next step |
| + output size, no memory step | no clip written; USB and thumbnail mode locked until a battery pull | a 3840 × 2560 clip whose rows 2304–2559 repeat rows 0–255 |
| + the memory step (first) | variant `_v2` (R16), then L5, L19, L16, XAVC-L 4:2:0 8-bit: every step DONE, no error after L5; `E95-311` after the last step; **REC crashed the camera, no clip** | `_v1` (D16): **clean 3840 × 2560, 23.98p, every row real picture; MXF header 3840 × 2560, 3:2** |
| Sensor step without its four timing words (tester 1's own build) | 20 s recorded, no fault, every frame black; the sensor register shadow did not match the full-height window | not run |
| LCD step | rapid left-right jitter | the picture split into three horizontal sections |

What follows from them:

- **The missing piece was memory** (next section). The first kit never checked the output buffers' size for the FX6, because the FX3 kit has no such step.
- **The first kit's order was wrong for the FX6.** It put the output size in second, before the encoder step and with buffers too small for it. The order is now memory, sensor, encoder, output size, which is the order that ran in issue 2 (there with the LCD step before the output size).
- **The MXF header fix works** on a real clip: StoredHeight / SampledHeight / DisplayHeight 2560, AspectRatio 3/2 (read from tester 2's file).
- **The LCD step does not work** on the FX6 as built. It is now only applied on request.
- **E95-311 comes with the sensor step** (on a camera). Tester 1 got it with the sensor step alone and no memory step, so the memory step is not the cause, and the memory variant did not avoid it. When it appears differs: at once (tester 2), after ~10 s of recording (tester 1, sensor step alone), after the last step (tester 1, full apply). Tester 1's build without the four timing words recorded without a fault, but the sensor then did not run full height (black frames), so it does not separate "timing" from "full height".
- **The FX6 never runs the full-height sensor mode itself** (observed). Register column 1 (sensor mode 0x01) is used by one drive mode only, 0xe011, a stills mode; the FX6 has no stills. On the FX3 and A7S III that mode runs whenever the camera is in stills, so the hardware around the sensor is exercised there. On the FX6 it is not. Inferred: E95-311 is the FX6's own check on something in that path. Which check is not known.
- **Where E95-311 comes from (observed, incomplete).** appFw's caution module (`procam/caution/caution_module.cpp`) prints `E%02X-%03X` from one 20-bit number (0x95311: class = bits 12–19, code = bits 0–11), read from a table the program builds at run time (in .bss), so the number is not in any file. No coprocessor code was found that sends 0x95 / 0x311. The coprocessor's log pages in the dumps hold boot lines only, and the camera's `/log` files are boot logs: neither recorded the event.
- The black band tester 1 saw with the sensor step alone is not explained either. Tester 2's final clips have real picture from the first row.

## The USB route (observed)

The kit talks to the camera the way the A7 IV, A7S III and FX3 kits do: the camera in Mass Storage, then Sony's service mode, where one small program file is written, loaded once by the camera and deleted again.

- The FX6's `libsencore.so` holds the same three login constants (other offsets) and the same four file commands; `libJiritsu.so` has the same loader for `/tmp/jiritsu/libJit.so`; the USB gadget modules are the same set.
- The main processor's device tree is byte-identical to the FX3's.
- The three functions the helper calls in `libsencore.so` (buffer alloc/free, the coprocessor transfer) are exported with the FX3's sizes, and their code differs only in relocated branch targets.
- `libmpr.so` and `libJiritsu.so` are loaded into the same process from the same module list as on the FX3, so the encoder step can reach `libmpr.so`.
- The FX6 asks "Connect USB Now?" when it is plugged in, and has a "Mass Storage (MSC)" USB function.
- `DeviceInfo.xml` is the same file on every body, so the helper checks which camera it is on itself: the hashes of three libraries and of four code and data pages (each differs from the same page on the FX3, A7S III, ZV-E1, A7C II, FX2, FX30 and A7 IV).

## The image processor: the FX3's imager code and tables (observed)

The FX6 6.02 coprocessor program (`cpapp-b.bin`, 17.9 MB) is a different, larger build than the FX3's, but its imager part is the FX3's:

- **Tables.** All 13 sensor tables the design touches are byte-identical to the FX3's (40 drive modes in the same order; 0x8c0 = 4K 23.98p is mode 12, 0xe011, the full-height mode the patch borrows, is mode 37), and so is the class table.
- **Code.** The drive-parameter calculator, the table map, the record selector, the scaler packers, the size-table set-up and the 24p/30p drive-mode choosers each match the FX3's function exactly (one hit, only relocated addresses differ).
- **Records.** The FX6's picture records are the FX3's at +0x1ac3c8 with relocated pointers, and one word more: +0x460 is 0x3ffe in all 46 FX6 records (the FX3 has a value per mode). It lies outside the bytes the design changes; the port keeps the FX6's value. Its meaning is not known.
- **Stored records.** The FX6's calculator gives all 40 stock records equal to the FX3's.
- **Register matrix.** The FX6's has the FX3's 489 rows in the same order with the same values, plus 7 all-zero rows. So column 1 is the same full-height sensor mode.
- **One structural difference:** the control object stores the drive-parameter pointer at +0x664 (the FX3: +0x698). The sensor step's library follows the FX6's chain (sensor object 0x14a5aec → +0x664), checked in emulation, including a case where only the FX3's offset holds the pointer: nothing is written.

| What | FX3 7.02 | FX6 6.02 |
|---|---|---|
| mode ids / column map / receiver types / timing | 0xc53790 / 0xc53538 / 0xc53fb0 / 0xc54190 | 0xe009fc / 0xe007a0 / 0xe0121c / 0xe013fc |
| windows / aux stream / LC / read-out | 0xd46fac / 0xd4759c / 0xd47b8c / 0xd47dbc | 0xe9b202 / 0xe9b7f2 / 0xe9bde2 / 0xe9c012 |
| 0x8c0 / 0x820 picture-record pair | 0xbb31d8 / 0xbb3d90 | 0xd5f5a0 / 0xd60158 |
| stored drive-parameter records | 0x1fdd574 | 0x2196504 |
| sensor object; drive-parameter pointer | 0x127ab68; control +0x698 | 0x14a5aec; control +0x664 |
| movie size table; the 3840 × 2160 word | 0x13c3190; 0x13c31c8 | 0x1626b7c; 0x1626bb4 |
| register matrix; shadow | 0xf09f84 (489 rows); 0xff4bf0 | 0x10ea3a8 (496 rows); 0x11d68b4 |
| table map; calculator; selector; size set-up | 0x857e5c; 0x331538; 0x2514b8; 0x4008ec | 0x85d36c; 0x3394ac; 0x261d10; 0x40793c |

## The memory step (first): `dmm7slot_fx6_v1`, and the variant `dmm7slot_fx6_v2`

**Found, built and first run by the tester of issue 2 (Mininoob).** What is here was rebuilt from the firmware's file and checked against that tester's two dumps (`tools/modding/fx6/build_dmm_fx6.py`).

**The cause (observed).**

- The output pictures live in units of memory id 0x2d9, DmmCfg key 0x3f1: 13,271,040 bytes each. The A7 IV, A7S III, FX3, FX2 and FX30 have the same units.
- The FX6 fills them at 1.5 bytes per pixel (on a camera: the repeat starts at row 2304 = 13,271,040 / (3840 × 1.5)). 3840 × 2560 then needs 14,745,600 bytes. The other bodies record 3840 × 2560 in the same units, at 1.25 bytes per pixel (12,288,000).
- The table is the camera's run-time copy of `/cp/DmmCfg.bin`: unit records at 0x213ef64, one 20-byte record `{0, type, key, size, attributes}` per unit, in file order. Tester 2's stock dump equals the file in all 1,147 records, so the addresses are the firmware's, not one camera's.
- Two layouts of the 106,954,752-byte parent block (key 0x39, three blocks) offer the unit: layout 0x26 (28 units of 3,317,760 bytes + one output unit; may be made once) and layout 0x28 (eight output units; may be made twice). Stock: 17 output units.

**The tester's ten words (`_v1`, on a camera).**

| Words | Change |
|---|---|
| 0x2141d10 … 0x2141d88 (seven) | layout 0x28, units 1–7: size 13,271,040 → 14,745,600 |
| 0x2141d98, 0x2141d9c | layout 0x28, unit 8: key 0x3f1 → 0x7fd (a key nothing asks for), size → 4,096 |
| 0x2141cac | layout 0x26, its output unit: size → 14,745,600 |

Layout 0x28 then totals 103,223,296 bytes and fits. Layout 0x26 totals 107,642,880: 688,128 bytes over the block.

**The FX6's own memory manager, emulated** (its code run alone on the file's table; `emu_dmm_server.py`, `dmm7slot_fx6_emu.json`):

| Table | What requests for an output unit get |
|---|---|
| stock | 17 units of 13,271,040; the first comes from layout 0x26 |
| the ten words | after a full release: **one refused request** (layout 0x26 is tried first and no longer fits), then 14 units of 14,745,600. No small unit is ever handed out |
| the nine words of layout 0x28 alone | the 13,271,040-byte unit of layout 0x26 is handed out first, among the big ones. Not shipped: one picture per cycle would overrun |
| `_v2`: the nine words + layout 0x26's unit retagged (0x2141ca8: key 0x3f1 → 0x7fd) | 14 units of 14,745,600, **no refusal**, no layout over its block |

So the tenth word is what keeps a small unit out of the pool, at the price of a refusal. Tester 2's camera ran with it and recorded. `_v2` was built to test whether that refusal is E95-311; it ran once (tester 1, XAVC-L): every step DONE, E95-311 all the same, then a crash on REC (see the table above). E95-311 also appears with no memory step at all, so `_v1` stays the default.

**How it is written.** The other kits' memory level refuses to write while the units are in use, which on an FX6 is always (no stills mode). So this step uses the word-writing level the output size and LCD steps use (16/17), as the tester did: D16 (`_v1`), R16 (`_v2`), and one put back D17 that holds the words of both. 23 guards from the file: the rest of every touched record, the end markers around layout 0x28, and the three parent records. On the tester's camera the words counted from the picture restart at the end of the USB session.

**While applied:** 14 output units instead of 17. Only QFHD has been run. With `_v1` a mode that needs layout 0x26 afresh is refused (the tester expects `EA0-000` there).

## Step 1, sensor: `ogsq_fx6_v1` (the FX3's `ogsq_fx3_v1`)

Rebuilt on the FX6's own image, not copied (`tools/modding/fx6/build_og_fx6.py`). Every check passes:

- the cell builder, run with the FX6's table addresses and the FX3 design's timing rows, gives its 19 cells at the FX6 addresses with the same bytes;
- the new record pair = the FX6's stock records with the FX3 design's changed bytes; the record model run with the FX6's own packers builds the same two records byte for byte;
- the 12-bit link-format rule holds on all 46 FX6 records and both new ones;
- the stored record of mode 0x8c0, with the cells applied, equals the FX3 design's (62 bytes).

19 cells + 2 records = 21 sites; the stored record at 0x2197554.

## Step 2, size: `outsz2560_fx6_v1` (the FX3's `outsz2560_fx3_v1`)

The FX6's size-table set-up, emulated, fills the FX3's 16 entries. One word, 0x1626bb4: 3840 × 2160 → 3840 × 2560, with the FX3's two guards.

**On a camera:** the word is right, but it must come last. Alone, or before the memory step, it makes the camera write 2560 rows into units that hold 2304 (see "What the first FX6 runs showed"). It is now the apply's last open-gate step.

## Which video mode the FX6 records QFHD 23.98p in (not settled)

The FX6's 24p drive-mode chooser is the FX3's byte for byte: for the QFHD size class it gives **0x8c0** (the mode this kit changes), or 0x28c0 if one settings flag is 2, and the Super 35 flag gives 0x8c4 / 0xbc4. The FX6's own application sets those flags; that part was not traced. **The debug dump reports the drive mode the camera ran before the session**, and the apply's closing dump says whether the sensor ran the open-gate mode (register column 1). If an FX6 records QFHD 23.98p in another mode (Cine EI, proxy recording or another setting may do that), the dump shows it and the design can follow.

## Step 3, encoder: `ogfile2560_xavc_fx6_v2` = `_v1` (49 data sites, made for the FX6) + the MXF header (4 code entries)

**Why the FX3's step does not carry over.** The FX6 records XAVC-I (AVC intra 4:2:2 10-bit) and XAVC-L (AVC long GOP) in MXF. None of the FX3's 689 encoder descriptors occurs in the FX6's `av-cam.bin`, and the FX6's `libmpr.so` is a 29 MB XDCAM-style MXF stack (the FX3's: 3.5 MB, MP4). What is shared (observed):

| Piece | FX6 6.02 | Same as the FX3 / A7 IV? |
|---|---|---|
| `mpr::g_videoParamComb` (the encoder request's size) | libmpr 0xcca018 | rows 0–11 byte for byte; row 0 = XAVC-L QFHD 4:2:0 8-bit, row 2 = XAVC-L QFHD 4:2:2 10-bit, row 9 = XAVC-I QFHD |
| `mpr::SetEncOpenParam` | libmpr 0x14c85c | copies the row's size into the request, as on the FX3 |
| unit-type table | av-cam 0x37815c, 7 rows | the FX3's first 7 rows |
| descriptor table | av-cam 0x3781cc, 589 × 0x90 | the FX3's layout, a different set |
| profile tables | av-cam 0x38cd1c (367), 0x3a3c1c (200) | the FX3's layout |
| clip-format table | av-cam 0x377658 | the A7 IV's codes (3840 × 2160 = 16) |
| matcher / memory function / start-block builder | av-cam 0x209898 / 0x201804 / 0x20559c | variants of the FX3's, run as the FX6's own |

The FX6's matcher does not compare chroma or bit depth: its quality class separates 4:2:2 10-bit from 4:2:0 8-bit.

**The design.**

| Kind | Sites | What |
|---|---|---|
| encoder request | 2 | `g_videoParamComb` rows 0 and 9: height 2160 → 2560 |
| descriptors | 12 | height → 2560 of every QFHD descriptor of XAVC-L 4:2:0 8-bit (#0, #19, #53, #54) and XAVC-I (#30, #41, #93, #98, #99, #103, #104, #114) at 23.98p and 25p, slow-motion rows included |
| profiles | 34 | their profiles: heights +0x06 and +0x38 → 2560; rows for the first encoder core +0x56: 1072 → 1280 where set |
| clip label | 1 | clip-format row 1 (8192 × 4320, unused on the FX6) → 3840 × 2560, code 16 (the QFHD code) |

Whole groups are changed so that a request at 3840 × 2560 reaches exactly the descriptor the same request reaches at 3840 × 2160 on a stock camera, whatever its other words (the request words the FX6 sends were not traced; emulated for 336 requests, all equivalent; 210 requests of other formats unchanged).

**Memory (emulated with the FX6's own memory function and its own codec firmware's calculation):** no unit-type site is needed (the FX3's had one). XAVC-I at 3840 × 2560 asks the same memory as stock; XAVC-L 4:2:0 at 3840 × 2560 takes the class a stock XAVC-L QFHD 120 fps slow-motion recording already uses, and its need fits (LD 29.5 of 33.8 MB). **XAVC-L 4:2:2 10-bit does not fit** (LD 39.4 MB of 33.8, multi 11.1 of 9.5; the FX3's blocks are 50.8 / 14.2 MB), so it is left out: its encoder stays at 2160 rows, and it must not be recorded while the kit is applied.

14 emulation checks pass on the FX6's own code: the matcher (and a Python model of it, checked against the real one on every descriptor), the memory function, the codec need for every changed descriptor, the start block (1072 → 1280 rows for the first core), the clip code.

**The MXF header (v2; the FX3 kit's metadata fix, for MXF).** Observed in libmpr 6.02 (compiled without optimisation, so every value passes through the stack):

- `muxMxfAvcFilePackageSectionPictureDescriptorCreate` (0x612dec, `muxMxfAvcFinalize.c`, called from `muxMxfAvcHeaderMetaDataCreate` 0x60c248) writes the picture descriptor of every XAVC MXF file: StoredWidth / StoredHeight / SampledWidth / SampledHeight / DisplayWidth / DisplayHeight / AspectRatio (local tags 0x3203 / 0x3202 / 0x3205 / 0x3204 / 0x3209 / 0x3208 / 0x320e), through `muxMxfCommonPutTag32bitValue` (0x699304) and its rational twin.
- The widths and the aspect come from a switch on the format's horizontal code: 3840 is code 0x12, with `mov w0, #0x10` / `mov w0, #9` (16:9) at 0x6131e0 / 0x6131e8; 4096 is code 0x1d (256:135).
- The heights come from a second switch on the vertical code: the 2160-line case (0x613388) is shared by 3840 and 4096.
- Both codes come from the recording format's metadata (`muxMxfAvcNrtMetaInfoGet` 0x60a98c), not from the encoder's size, so the encoder step's 2560 does not disturb them. The HD muxer and the trimming tool have their own writers, not on the XAVC recording path.

The design: the QFHD aspect 16:9 → **3:2** (two words, reached only by the 3840 case), and the 2160-line case rewritten in its own 8 instructions to give **2560 when the stored width is 3840**, 2160 otherwise (so DCI 4K keeps 4096 × 2160); it ends in the 1080p case's tail, which sets the same line map as the stock 2160 case. 7 instruction guards; written by the helper as the FX3's and A7 IV's header fixes are (code in libmpr's first segment, through `/proc/self/mem`).

**Emulated with the FX6's own writer** (`build/emu_mxf_meta_fx6.py`, 30 cases: every format code with its line codes, progressive and interlaced, both codec types): QFHD 3840 × 2160 16:9 → **3840 × 2560 3:2** (stored, sampled and display height); DCI 4096 × 2160, 2K, 1920 and 1280 byte-identical to stock; the tag set keeps its size. One path differs besides QFHD: Sony's own fall-through from the 2048 case (codec type ≠ 4) into the 3840 case, which stock already labels 3840 wide; its aspect reads 3:2. No FX6 XAVC format is 2048 wide, so no FX6 recording takes it.

Not changed: Sony's XML (NonRealTimeMeta, inside the file and the M01.XML sidecar) keeps 3840 × 2160, 16:9, as on the FX3 and the A7 IV; the level label. `open_gate_apply_no_meta.cmd` applies v1 (N19): the MXF header then keeps 3840 × 2160, 16:9. The put back (L20) restores either.

**In-camera playback (read, not changed):** the FX6's decode set-up has the FX3's form for the XAVC codecs (4096 × 2160 rows with the 4K memory; the 8K row and memory only for two other codecs), so 3840 × 2560 clips are expected to fail to play, as on the FX3.

**Risks for the camera:** that the codec and the MXF muxer accept a 2,560-row AVC stream (they do on the FX3 in MP4); that nothing else in the FX6's MXF writing checks the descriptor's height against the 2160-line format (none was found); the level label (5.1/5.2) below the picture size, as on the FX3; MXF index and bit-rate handling for XAVC-I with a bigger picture at the same per-frame budget; XAVC-L 4:2:2 10-bit recorded by mistake.

## Step 4, the LCD: `lcd32_fx6_v1` (made for the FX6; 8 words)

**Why the FX3's fix is not enough.** On the FX3 (4:3 panel) the fix changed the height of a 16:9 picture from width × 9/16 to width × 2/3. On the FX6, a 16:9 picture on a 16:9 panel is always shown full screen: the fit function returns "fill" before it reads the ratio. The firmware does pillarbox a 16:9 picture on one panel code (5).

**What the step changes:**

| Word | Stock → new | What |
|---|---|---|
| 0x1dbb44 | 1 → 8 | panel-type table (LCD and the second output), type 1 (16:9 panel): panel code 2 → 5, the code that pillarboxes a 16:9 picture |
| 0x1db34c, 0x1db350 | 9/16 → 2/3 | the 16:9 picture's ratio: the function's own 3:2 case |
| 0x60b354, 0x60b358 | 3/8 → 1/3 | de-squeeze 2.0x: the whole 3:2 frame at 3:1 (the FX3 owner's choice) |
| 0x60b35c, 0x60b360 | 45/104 → 20/39 | de-squeeze 1.3x: 1.95:1 |
| 0x60cf40 | `cmp r0, #4` → `#5` | the 2.0x centre crop off |

30 guards, none overlapping a site. Emulated on the FX6's whole layout function (43 cases): on a 1280 × 720 panel the live view goes from (0, 0, 1280, 720) to **(100, 0, 1080, 720)**, a 3:2 box with 100-pixel bars; 960 × 540 → (76, 0, 808, 540); a 4:3 or 3:2 panel also gives 3:2. 4:3 and 3:2 pictures are unchanged everywhere; HDMI on a 16:9 output is unchanged.

**Side effects while applied (emulated):** a DCI 17:9 picture fills the LCD (6% too tall); the de-squeeze shapes are the 3:2 picture's on every output that de-squeezes (the calculator is shared); an HDMI/SDI output set to a 4096-wide resolution pillarboxes a 16:9 picture at 3:2.

**On a camera: it does not work.** Both testers' dumps show panel type 1 (16:9), and tester 1's dump after the step shows the eight words as designed. Both saw a broken preview: rapid left-right jitter (tester 1, in the state without the memory step) and the picture in three horizontal sections (tester 2, while recording correctly). Without the step the preview is stable. The recording is not affected. The emulation covers the layout function's rectangle, not what the display hardware does with it. The stock FX6 never shows a picture narrower than its LCD (a 16:9 picture on a 4:3 output is letterboxed, full width), so the pillarbox path may simply not be supported by the LCD's drive. Not settled: no dump of the final state with the step in exists yet. The step is applied only by `open_gate_apply_with_screen.cmd`.

**Not known:** that the LCD is the firmware's device 1, that the menu's 1.3x / 2.0x send codes 1 / 4, and how the FX6 draws focus frames and markers (it has none of the FX3's frame tables; a plane laid out for the 16:9 frame could be off by up to 100 px at the edges).

## The kit

- **Read-only helper** (`helper_fx6/fx6read.c`, made from fx3read.c by text changes): identity, every site's state, and in the dump build the debug pages: the sensor register shadow and matrix, the stored records, the size table, the coprocessor's own logs, the scaler state (ported from the FX3 dump's addresses), the camera core's last log record (the drive mode it ran before the session), and the LCD pages (panel type bytes, the ratio and de-squeeze words, the de-squeeze scale). Since the second kit (`fx6read_v2`): the eleven memory words, the memory table's pages (the report lists both layouts and whether each fits), and the files of `/log/cp`.
- **Write libraries:** the A7 IV helper's levels 5/6, 16/17 and 19/20 (`helper/readcheck.c`, unchanged), with the FX6's tables. The libraries of the first kit are byte for byte the same in the second; D16, R16 and D17 are new.
- **Emulation of the libraries** (`helper_fx6/emu_fx6.py`, `emu_fx6_write.py`): apply, apply again, put back byte for byte, foreign bytes, lost writes undone, every guard; the read-only libraries refuse an FX3 or A7S III image; the FX3, A7S III and ZV-E1 kits' check libraries say NOT READY on an FX6, and the FX3 and A7S III kits' write libraries write nothing on an FX6.
- **Scripts:** `fx6_run.py` / `fx6_apply.py` (from the FX3's). The FX6 has no stills mode: each step writes during a USB session, while the picture is stopped (on the A7S III and FX3 the sensor sleeps during a session and the picture is started afresh after it). The apply ends with the debug dump after an unplug and replug.

## Not known yet

- What raises E95-311 (it comes with the sensor step's full-height state; the memory variant does not avoid it), and whether it matters for recording (XAVC-I recorded through it on one camera).
- Why the LCD step breaks the preview, and how to show 3:2 on the FX6's LCD.
- Why XAVC-L crashed on REC (one run, with `_v2` and E95-311 already showing): the codec at 2560 rows, 14 output units for long-GOP, the variant, or that camera. A run of XAVC-I with `_v1` on tester 1's camera would separate them.
- The apply's exact order without the LCD step (the run in issue 2 had the LCD step between the encoder and the output size).
- Why the sensor step alone gave tester 1 a black band at the top of the squeezed picture.
- Whether the power switch removes the patch (it does on the A7S III).
- HD, DCI 4K and S&Q while the memory step is applied.

Settled by the testers: the FX6 runs QFHD 23.98p FF in drive mode 0x8c0; the LCD's panel type is 1; the picture restarts with the patch after a USB session; the MXF muxer accepts 2560 rows.
- Exposure, autofocus, Cine EI, S-Log3, long recordings, card speeds, SDI/HDMI output in the open-gate state.
- In-camera playback of the clips (it fails on the FX3; not traced for the FX6's MXF playback).
