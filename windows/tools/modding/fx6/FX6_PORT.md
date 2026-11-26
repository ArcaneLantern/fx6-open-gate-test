# FX6 6.02 port of the FX3 open-gate kit (working notes)

Build `fx6_602` (ILME-FX6, firmware 6.02; `downloads\FX6 firmware 6.02\BODYDATA.DAT` = the registered
`camera_re\fx6\firmware 6.02\BODYDATA.DAT`, SHA-256 dbb814d5…c339, crypter CXD90057_k0; extracted and indexed since 2026-11-12).
Started 2026-11-26 at the owner's request: port the FX3's working open gate (and the metadata fix) to the FX6, with Windows, macOS and
Android kits and the debug dump for testers; repo `A7iv Firmware\fx6-open-gate-test`. The owner: the FX6 LCD is 16:9, black bars at the
sides for a 3:2 picture are fine.
**Reference: the FX3 kit** (open gate works on two FX3s, 2026-11-24; [[fx3-open-gate-port]]), itself the A7S III's proven v5 kit.
Companion notes: `FX6_PORT_ENCODER.md` (encoder side and file headers), `FX6_PORT_SCREEN.md` (the LCD step).
~~NOTHING HAS RUN ON AN FX6.~~ Two FX6s ran the first kit on 2026-11-25/26 (repo issues 1 and 2): see the next block.

**SECOND KIT, 2026-11-26 (after the testers' first runs; the owner: "look why his suggestions fixed his version, and integrate ... fix open
gate properly"). Published to `fx6-open-gate-test` with APK 0.2; not committed by me, not run.**
- **What the testers showed.** Tester 1 (issue 1, macOS, XAVC-L): L5 alone works (column 1, 0x8c0, a clip; a ~210-row black band at the top
  of the squeezed picture, not explained); + L16 = no clip, USB locked. Tester 2 (issue 2, Mininoob, XAVC-I): first kit recorded 3840x2560 with
  rows 2304-2559 repeating rows 0-255; with their own ten-word memory step first, **clean 3840x2560** (I decoded 72 consecutive frames of
  THICCFX6-0143.MXF: no bad frame; its MXF descriptor reads 3840x2560 3/2, so header fix v2 works on a camera). Left over: `E95-311` after L5
  (picture black, beeps, lamp; back after the next step; code latched), and S16 scrambles the LCD on both cameras.
- **Cause.** The FX6 fills an output unit (id 0x2d9, key 0x3f1, 13,271,040 bytes, the same unit as every other body) at 1.5 bytes/pixel: 3840x2304.
  The A7 IV / A7S III / FX3 use 1.25 (12,288,000 for 2560 rows), which is why the FX3 kit has no memory step and I never checked. **The FX2 / FX30 /
  A1 II ports each had a DMM size check; this port skipped it.**
- **Memory step** (`build/build_dmm_fx6.py`; `parse_dmmcfg.RAM["fx6_602"]`, `emu_dmm_server` fx6_602 explicit entry; evidence
  `evidence/fx6/dmm7slot_fx6_emu.json`, the tester's table pages in `evidence/fx6/issue2`): unit records at RAM 0x213ef64..0x2144900 = the file,
  1,147 records (tester's stock dump). Layout 0x26 = 28 x key 0x3f6 + 1 x 0x3f1 (limit 1), layout 0x28 = 8 x 0x3f1 (limit 2), parent key 0x39
  106,954,752 x 3. The FX6 reader's key limit is **0x800** (A7 IV 0x900): 0x8fe is fatal here, the tester's 0x7fd is fine.
  - `dmm7slot_fx6_v1` = the tester's ten words (D16). In the FX6's own allocator: after a full release ONE REFUSED REQUEST (0x26 tried first,
    over its block by 688,128), then 14 x 14,745,600. The tenth word (0x2141cac) is what keeps 0x26's small unit out of the pool.
  - `dmm7slot_fx6_v2` (R16, `--alt-memory`, NOT RUN): 0x2141ca8 key -> 0x7fd instead; no refusal, nothing over its block, 14 units.
  - The nine 0x28 words alone hand out 0x26's 13,271,040 unit first: NOT shipped (the owner chose "ship both" when the variant was still the
    nine-word idea; the emulation then showed that idea is worse, so the variant became the retag).
  - `dmm7slot_fx6_back` = the 11 words of both, for D17 (level 17 skips a site that is already stock).
  - Level 13 (other kits' DMM engine) refuses while units are in use = always on an FX6, so D16/R16/D17 are level 16/17 word libraries.
- **Order**: apply D16, L5, L19, L16 (+ S16 only with `--screen`); putback S17, L17, L20, L6, D17 (`--no-screen` drops S17). The first kit's
  L5, L16, L19 put the output size in before its units and its encoder: that is issue 1's "no clip".
- **E95-311: NOT explained.** appFw only formats it (`E%02X-%03X`, procam/caution/caution_module.cpp); no raise site found by constant
  search. Tester 1's kprint pages hold boot lines only (no run-time log there). Hypothesis to test: v1's refused request at the first full
  re-allocation (the sensor-mode change) -> R16. Other candidate: XAVC-I vs XAVC-L. The dump now copies `/log/cp/*` (8 KB each).
- **LCD: NOT explained.** Tester 1's dump after S16 shows the 8 words as designed and panel type 1; preview jitters / splits in three. The
  emulation covers the rectangle only. S16 is opt-in.
- **Also**: `fx6read_v2` (11 dmm sites hard, 7 table pages, /log/cp); the report decodes the table (both layouts, fit) and no longer lists
  the benign `read failed -21` / `truncated` lines; `kit.json` panel-table text fixed (u32 words ff000000 01000000 00000000 02000000);
  `fx6_run.py` got the FX3 runner's leftover-library handling (`KNOWN_LIBS`, `--remove-library`); apply needs a check made with fx6read_v2;
  publisher prints which macOS files are not 100755 in git (issue 1: run.sh).
- **Pins**: check 644b463c, dump 6bfc25e9, D16 32a2bbc5, R16 28f18221, D17 762ca5ac; L5/L6/L16/L17/L19/L20/N19/S16/S17 unchanged (rebuilt,
  same hashes: readcheck.c untouched). APK 0.2 8a79e588.
- **Checks that pass**: build_dmm_fx6 (asserts incl. the two dumps), emu_dmm_server --selfcheck fx6_602, emu_fx6 (20 cases + 3 foreign),
  emu_fx6_write (all, incl. 31 new memory-step cases and the ZV-E1 / FX2 L13 libraries writing nothing), 14 `--selftest`, the dry runs, the
  publisher's checks, the app harness (7).
- **Proposed, not built**: one-connection apply (all steps in one USB session: `adj_cmd_set_file2` loads and closes the library per write, so
  several can run in one session; needs `ct6_level1_run.py`, shared by every kit).

**State of the FIRST kit, 2026-11-26: built, emulated, published to `fx6-open-gate-test`.** Steps: apply = L5 `ogsq_fx6_v1`,
L16 `outsz2560_fx6_v1`, L19 `ogfile2560_xavc_fx6_v2`, S16 `lcd32_fx6_v1`, then the read-only debug dump; putback = S17, L20, L17, L6;
`--no-meta` = N19 (`ogfile2560_xavc_fx6_v1`).
- **Encoder** (`FX6_PORT_ENCODER.md`): XAVC-I QFHD and XAVC-L QFHD 4:2:0 8-bit at 23.98p/25p, 49 data sites (2 libmpr comb heights, 12
  descriptors, 34 profile words, the clip label). **XAVC-L 4:2:2 10-bit left out** (its codec memory at 2560 rows exceeds the FX6's LD/multi
  blocks). FX6 playback has the FX3's 4K-decode form: clips expected not to play in camera.
- **MXF header fix (v2, the owner: "Yes, build it")**: `build/mxf_meta_sites_fx6.py`, `build/build_ogfile_fx6_meta.py`, emulated by
  `build/emu_mxf_meta_fx6.py` (the FX6's own `muxMxfAvcFilePackageSectionPictureDescriptorCreate` 0x612dec, 30 cases): QFHD aspect 16:9 -> 3:2
  (0x6131e0 / 0x6131e8, format case 0x12 only) and the 2160-line case 0x613388 rewritten (8 instructions) to give 2560 when the stored width is
  3840 (DCI 4096 keeps 2160); descriptor = 3840x2560 3:2, every other format byte-identical. Sony's XML unchanged (as FX3 / A7 IV).
- **LCD** (`FX6_PORT_SCREEN.md`): 8 words, 30 guards; panel type 1 mapped to the firmware's pillarbox panel code 5, 16:9 ratio 9/16 -> 2/3,
  de-squeeze 1.3x 20/39 and 2.0x 1/3, 2.0x crop off. Emulated: 1280x720 LCD shows (100, 0, 1080, 720).
- **Pins** (fx6_run.py; header `fx6read_v1`): check 352d21b7, dump fdda69f8, L5 5ed7dfb6, L6 102864a6, L16 2c405ab7, L17 08289301,
  L19 bc85507f (v2), L20 b225df8a, N19 7033d38a (= v1's L19), S16 2d775ea9, S17 d336fcd1. APK 0.1 (`android_app_fx6`, com.fx6.opengate).
  (Before the header fix, same day: check 6c3a5cb5, dump 49a3a59d, L19 7033d38a, L20 0fe66a56; never published with an APK that ran.)
- **Checks that pass:** build_og_fx6 (all asserts), build_ram_words_fx6, emu_lcd_fx6 (43), emu_ogfile_fx6 (14), emu_fx6 (14 + 3 foreign kits
  NOT READY), emu_fx6_write (every case: L5/L6 incl. the FX3-offset trap and three camera-held records, L16/L17, L19/L20 with 15 + 3 guards,
  S16/S17 with 30 guards, the FX3 and A7S III kits' L5/S16/L19 write nothing on an FX6), all 10 `--selftest`, the apply/putback dry runs, the
  publisher's checks in the published tree, the macOS takeover tests, and a PC harness of the app's Python side on the APK's payload (6).
- **To be learnt from the first tester:** the drive mode FF QFHD 23.98p runs (want 0x8c0), the LCD panel-type byte (want 1), that the
  picture restarts patched after the last USB session, whether the codec/MXF muxer accept the 2560-row stream, the power switch.

## Rebuild, in order

1. `C:\Python313\python.exe -B build\check_fx6_service_route.py` -> `evidence\fx6\service_route.json` (USB route: keys, Jiritsu, modules)
2. `C:\Python313\python.exe -B build\emu_drvparam.py fx6_602 --json evidence\fx6\drvparam_stock_fx6_602.json` (CONSTS entry fx6_602)
3. `C:\Python313\python.exe -B build\build_og_fx6.py` -> `ogsq_fx6_v1` + `evidence\fx6\ogsq_fx6_v1_checks.json`
4. `C:\Python313\python.exe -B build\build_ram_words_fx6.py` -> `outsz2560_fx6_v1` (emu_size_table entry fx6_602)
4b. memory (second kit): `C:\Python313\python.exe -B build\emu_dmm_server.py --build fx6_602 --selfcheck`, then
   `C:\Python313\python.exe -B build\build_dmm_fx6.py` -> `dmm7slot_fx6_v1` / `_v2` / `_back` + `evidence\fx6\dmm7slot_fx6_emu.json`
   (it also checks the tester's two table dumps in `evidence\fx6\issue2`)
5. encoder: see `FX6_PORT_ENCODER.md`; screen: `work\venv\Scripts\python.exe -I -B build\build_lcd_fx6.py`, `C:\Python313\python.exe -B build\emu_lcd_fx6.py --save`
6. `camera_tests\CT6_memory_read_check\helper_fx6`: edit `kit.json` when a design changes; `work\venv\Scripts\python.exe -I -B gen_fx6.py`,
   `bash build_fx6.sh check|dump <out>`, `C:\Python313\python.exe -B emu_fx6.py`; `work\venv\Scripts\python.exe -I -B gen_fx6_write.py`,
   `bash build_fx6_write.sh`, `C:\Python313\python.exe -B emu_fx6_write.py`
7. Re-pin in `fx6_run.py` (PINS, WRITE_STEPS); `C:\Python313\python.exe -B fx6_run.py <step> --selftest`; `work\venv_camera\Scripts\python.exe -B fx6_apply.py apply --dry-run`
8. `work\venv\Scripts\python.exe -I -B publish\publish_fx6.py --include-write`; `work\venv_camera\Scripts\python.exe -I -B android_app_fx6\sync_payload.py`;
   `Set-Location android_app_fx6; .\gradlew.bat assembleDebug`; publish again (the APK is copied only if its payload is the published tree)

## What the FX6 shares with the FX3 (all read from the 6.02 files)

**USB service route** (`build/check_fx6_service_route.py`, `evidence/fx6/service_route.json`):
- `libsencore.so` holds the three 512-byte login round constants (at 0x5c090 / 0x5c290 / 0x5c490; the FX3's at 0x55380…), the
  authentication names and the four Jiritsu file commands (JIRITSU_SET_FILE_PATH, _SET_FILE2, _GET_FILE2, _FILE_DELETE2).
- `libJiritsu.so` has the library loader strings (`/tmp/jiritsu/libJit.so`, the RAM-disk copy, `/tmp/jbusy`, dlopen).
- The USB gadget modules are the FX3's set (usbg_sen.ko, usbg_storage.ko, usb_f_mass_storage.ko, …; other builds of the same files).
- The main processor's device tree (`update/0800_appli/setting/cxd90057.dtb`) is byte-identical to the FX3's.
- The helper's three imports (`dmm_alloc`, `dmm_free`, `sen_dma_transfer`) are exported by the FX6's libsencore with the FX3's sizes;
  their code differs only in relocated branch targets.
- libmpr.so and libJiritsu.so are both loaded from the module list in `libIMDB.so`, as on the FX3, so the encoder step's
  `/proc/self/mem` writes reach libmpr in the process that loads the helper.
- appFw: `FUNC_procam_start_mass_storage_function`, the updater sequence, UI strings "Connect USB Now?" and "Mass Storage (MSC)".
- `DeviceInfo.xml` is the same file on every body (the helper checks the body itself).
- Kernel command line (appli kemco.txt): av-cam reserved at `memrsv=0x01000000@0x401000000:ex`, as on the FX3. Differences: the FX6
  has `exception.stop=0 exception.reboot=0 wdt.mode=0` where the FX3 has 1/1/1 (not traced).

**Coprocessor imager code and tables** (`cpapp-b.bin`, 17,952,816 bytes, SHA-256 b432af72…def6, loaded at 0x108000):
- All 13 sensor tables of the FX3 design are byte-identical in the FX6 image (40 drive modes, same order: 0x8c0 = index 12,
  0xe011 = index 37), and the class table:

| What | FX3 7.02 | FX6 6.02 |
|---|---|---|
| mode ids / column map / receiver types / timing (A, B = A + 0x3c0) | 0xc53790 / 0xc53538 / 0xc53fb0 / 0xc54190 | 0xe009fc / 0xe007a0 / 0xe0121c / 0xe013fc |
| rx2 / d / crop / class | 0xc54910 / 0xc54b90 / 0xc53830 / 0xc53b50 | 0xe01b7c / 0xe01dfc / 0xe00a9c / 0xe00dbc |
| windows / aux stream / LC / read-out | 0xd46fac / 0xd4759c / 0xd47b8c / 0xd47dbc | 0xe9b202 / 0xe9b7f2 / 0xe9bde2 / 0xe9c012 |
| geometry row of 0x8c0 | 0xbfb188 | 0xda6568 |
| 0x8c0 / 0x820 picture-record pair | 0xbb31d8 / 0xbb3d90 | 0xd5f5a0 / 0xd60158 (every record: FX3 + 0x1ac3c8) |
| 0xa000 still pair | 0xbc3f60 / 0xbc4b18 | 0xd70328 / 0xd70ee0 |
| stored drive-parameter records (0x15c each) | 0x1fdd574 | 0x2196504 (index 12 at 0x2197554) |
| sensor object (getter); drive-parameter pointer | 0x127ab68 (0x85617e); control +0x698 | **0x14a5aec (0x85b640); control +0x664** |
| movie size table; the 3840 × 2160 word | 0x13c3190; 0x13c31c8 | 0x1626b7c; 0x1626bb4 |
| register matrix; its shadow | 0xf09f84 (489 rows); 0xff4bf0.. | 0x10ea3a8 (496 rows); 0x11d68b4.. |

- **Code, matched one to one** (`build/match_thumb.py fx3_702 fx6_602`, a single exact masked hit each): table-map caller 0x85d36c
  (FX3 0x857e5c, 110 of 110 instructions aligned, only table addresses differ), constructor 0x85e742, constructor block 0x85d402–0x85d54e
  (configuration at +0x548 as the FX3; fields from +0x664 on sit 0x34 lower than the FX3's), calculator 0x3394ac, log print 0x9e8768,
  record selector 0x261d10, packers CamArc 0x25def0 / CamNrs 0x6d0a74 / CamSig 0x6d6d9a / CamLrc 0x6d0a30 / Dev 0x6cffa8 / 0x6cfe4a,
  fit 0x6d69f8, size-table set-up 0x40793c, 24p drive-mode chooser 0x40e518 (the FX3's 0x407b2c byte for byte), 30p chooser 0x40e644.
- **The top drive-mode selector** 0x40db6c is the FX3's 0x407150 with its settings-block offsets 4 bytes later (+0x630 → +0x634 …).
  The 24p chooser gives the QFHD class (index 3) 0x8c0, or 0x28c0 if [settings+0x6a8] == 2, and the Super 35 flag gives 0x8c4 / 0xbc4.
  Which values the FX6's appFw puts there was NOT traced: the dump's core log record reports the drive mode the camera ran.
- **Stock stored records:** emu_drvparam on the FX6 gives all 40 records equal to the FX3's.
- **Picture records:** every FX6 record is the FX3's + 0x1ac3c8 with relocated pointers, and one value word: +0x460 is 0x3ffe in all 46
  FX6 records (the FX3 has a value per mode, 0..0x20b). It is not one of the design's changed bytes; the port keeps the FX6's value.
  Meaning unknown.
- **Register matrix:** the FX6's holds the FX3's 489 rows in the same order with the same 12 columns, plus 7 all-zero rows after row
  59 (`evidence/fx6/matrix_alignment.json`), so column 1 is the same full-height sensor mode.

## The sensor step `ogsq_fx6_v1` and the size step `outsz2560_fx6_v1`

`build/build_og_fx6.py` rebuilds the FX3's `ogsq_fx3_v1` on the FX6's own image and checks (all pass, `evidence/fx6/ogsq_fx6_v1_checks.json`):
- the cell builder (`build_og_s3_v3.cells`, v4's timing rows 313 × 4788 P57 E34 and 313 × 4780 P239 E193, both E < P) gives the FX3
  design's 19 cells at the FX6 addresses with the same bytes;
- the record selector maps every mode to the FX3's record + 0x1ac3c8; the new pair = FX6 stock records + the FX3 design's changed bytes;
- the record model with the FX6's own packers rebuilds both new records byte for byte (and the FX3 model reproduces the FX3 design);
- the 12-bit link-format rule holds on all 46 FX6 records, both new records pass it;
- the stored record of index 12 with the cells applied (plus 16/19 and the run-time bytes left alone) equals the FX3 design's: 62 bytes.
Result: 19 cells + 2 records = 21 sites, 6,092 bytes; stored record 62 bytes at 0x2197554.

`build/build_ram_words_fx6.py`: the size table emulated on the FX6 image holds the FX3's 16 entries; site 0x1626bb4 (3840 × 2160 →
3840 × 2560) with two guards, as on the FX3.

## The kit

- **Helper:** `helper_fx6/fx6read.c` = fx3read.c with text changes only; `gen_fx6.py` writes its header (identity: libmpr / libsencore /
  libJiritsu hashes and code pages 0x128000, 0x4a8000, 0x85d000 + constant-data page 0xae7000, each different from the page at the same
  address in the FX3, A7S III, ZV-E1, A7C II, FX2, FX30 and A7 IV images). The dump reads the FX3 dump's pages at their FX6 addresses
  (shadow 0x11d6000, matrix 0x10ea000, size table 0x1626000, records 0x2196000, the coprocessor logs 0xe0000 / 0xc0000, scaler state
  ported with `build/port_addr.py fx3_702 fx6_602`: context 0x13af000, resize work 0x13c2000, division block / core log record / settings
  0x1639000.., write-buffer ring 0x13a6000) and the LCD pages of `FX6_PORT_SCREEN.md`.
- **Write libraries:** readcheck.c levels 5/6 (`-DIMAGER=0x14a5aec -DCTRL_DRVPARAM=0x664`), 16/17 (size; and S16/S17 with the LCD words),
  19/20 (encoder) — `helper_fx6/build_fx6_write.sh`. readcheck.c is unchanged.
- **Scripts:** `fx6_run.py` / `fx6_apply.py` from the FX3's. The FX6 has no stills mode: the procedure is FF, QFHD 23.98p, "Connect USB
  Now?" → Execute, and the USB session itself stops the picture (as on the A7S III/FX3: sensor asleep during a session, picture started
  afresh after it). The apply ends with the read-only dump after an unplug/replug: the debug dump testers send back (drive mode, register
  column, scaler state, LCD words).
- **Android:** `android_app_fx6` (app id com.fx6.opengate, `Fx6Activity`, `og_fx6.py`), from android_app_fx3 without the S-I box and the
  playback buttons. **macOS:** the A7S III/FX3 macOS kit (`publish/a7siii_macos.py`) with the FX6 launchers.
- **Publisher:** `publish/publish_fx6.py --include-write`.
