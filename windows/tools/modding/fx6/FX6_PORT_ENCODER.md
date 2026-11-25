# FX6 6.02 port: the encoder and container side (working notes, 2026-11-26)

Build `fx6_602` (ILME-FX6, firmware 6.02, `downloads\FX6 firmware 6.02\BODYDATA.DAT` = the registered `camera_re\fx6\firmware 6.02\BODYDATA.DAT`,
sha256 dbb814d5…c339). Part of the owner's request to port the FX3 open gate to the FX6. This file covers the main processor only (av-cam.bin and
libmpr.so): the counterpart of the FX3 kit's L19 step. Static reading and emulation only; nothing has run on an FX6.

**Result: design `ogfile2560_xavc_fx6_v1`, 49 sites / 132 bytes (libmpr 2 sites, av-cam 47), all data, no code. All 14 emulation checks pass
(`build/emu_ogfile_fx6.py` → `evidence/fx6/ogfile_fx6_emu.json`).** XAVC-I QFHD and XAVC-L QFHD 4:2:0 8-bit at 23.98p and 25p.
**XAVC-L QFHD 4:2:2 10-bit is left out** (codec memory, below). **The MXF-header fix (a "v2") is not built** (below).

Rebuild: `C:\Python313\python.exe -B build\build_ogfile_fx6.py --list`, then `C:\Python313\python.exe -B build\emu_ogfile_fx6.py`.
Design JSON sha256 734696a5f734a9bb1c155880a14147e2767053548ecdc730bd8151785965c73c (rebuilds byte for byte).

## What the FX6 records, and why the FX3 tables do not carry over

The FX6 records XAVC-I (AVC intra 4:2:2 10-bit) and XAVC-L (AVC long GOP) in MXF. None of the FX3's 689 av-cam descriptors occurs in the FX6's
av-cam byte for byte, and the FX6's libmpr.so is a 29 MB XDCAM-style MXF stack (the FX3's is 3.5 MB, MP4). What *is* shared:

| Piece | FX6 6.02 | Same as the FX3 / A7 IV? |
|---|---|---|
| `mpr::g_videoParamComb` (dynamic symbol) | libmpr 0xcca018, 20 rows × 0x18 | rows 0–11 byte for byte; rows 12–16 MPEG-2 (codec 4), 17 XAVC-I DCI, 18–19 HD |
| `mpr::pconv::m_vpcSt` | libmpr 0xec1fd8, 20 rows × 0x1c | same meaning (row 9 has the intra flag) |
| `mpr::SetEncOpenParam` | libmpr 0x14c85c | copies the row's raster to EncOpen +0x68/+0x6a (`ldrh [x24,#4]/[x24,#6]` → `strh [x19,#0x68]/[x19,#0x6a]` at 0x14ca58–0x14ca64; GOT slot 0x108f1d0 relocates to 0xcca018) |
| unit-type table | av-cam 0x37815c, **7 rows** | rows 0–6 are the FX3's byte for byte (the FX3 has 10) |
| descriptor table | av-cam 0x3781cc, **589** × 0x90 | the FX3's layout; a different set (codecs 5 = AVC long GOP, 8 = AVC intra, 6/7 MPEG-2, 0x11/0x13/0x14/0x15 proxies/HD, 0x19/0x1a 8K) |
| profile tables | av-cam 0x38cd1c (367 rows), 0x3a3c1c (200 rows) | 0x100-byte rows, each table ending with a key-0 row (codec 0x1c); a one-row codec-6 table follows at 0x3b041c |
| clip-format table | av-cam 0x377658, 18 rows of {valid, w, h, code} | the A7 IV's codes: row 1 8192x4320 code 1, row 5 3840x2160 code 16 (the FX3's are 3 / 23) |
| allocator | av-cam 0x210f3c | = A7 IV 0x222bd0 exactly (`avcam_fnport.py`); log 0x261720 = A7 IV 0x27278c |
| matcher | av-cam 0x209898 | **a variant** (below) |
| memory function | av-cam 0x201804 | a variant (below) |
| clip-format function | av-cam 0x19e4bc | reads the libmpr packet (+0x68/+0x6a raster, +0x81 valid byte), not the converted request |
| start-block builder | av-cam 0x20559c, called at 0x2032c8 | found by the A7 IV's six instructions before the call (as on the FX3); 643 of 803 instructions equal to the FX3's 0x221b50 |
| enc-open handler | av-cam 0x201ce4 | copies 0x88 bytes of the request to ctx+0xe110, then the matcher (via 0x202740) |
| codec firmware | `codec/vcd_firmware_imola2.bin` | **differs** from the A7 IV/FX3 file (2.58 M bytes differ); its channel-memory calculation 0x800663f4 starts as the A7 IV's (24 words equal, branch targets and immediates aside), its getters are the A7 IV's instructions 0x18 bytes further on |

Formats → comb rows (from the comb rows' own fields, m_vpcSt, and the MXF format fill 0x548a3c below):
row 0 = XAVC-L QFHD 4:2:0 8-bit, row 2 = XAVC-L QFHD 4:2:2 10-bit, row 9 = XAVC-I QFHD, row 17 = XAVC-I DCI 4096x2160.

## The FX6 matcher (0x209898), read from its code

It compares, for each descriptor in order: codec (+0), coding rate (+8), +0xc, quality class (+0x10) and the raster (+0x7e/+0x80). **Unlike the
FX3/A7 IV matcher it does not compare chroma (+0x14) or bit depth (+0x18)**: on the FX6 the quality class tells 4:2:2 10-bit from 4:2:0 8-bit
(XAVC-L 0x15/0x18 = 4:2:2 10-bit, 0x17/0x1a = 4:2:0 8-bit; 0x15/0x17 only exist at 59.94/50p, 0x18/0x1a at 29.97/25/23.98p). Then, with
`path A = (req+0x88 & ~1) != 2 or req+0x8c == 12` (every FX6 descriptor list is all 12s, so path A whenever +0x8c is 12):

- +0x88 ∈ {2, 5}: the first matching descriptor whose +0x24 is not 1. Every XAVC-L QFHD row has +0x24 = 1, so a stock XAVC-L request with
  +0x88 = 2/5 finds nothing: **XAVC-L recordings must send another value**. XAVC-I with 2/5 reaches the 1xxxxx UseCore-2 rows (#30/#41).
- otherwise: input rate: a request at rate 0 needs a descriptor with rate 0; a request at rate r needs a descriptor with rate −1 or ≥ r.
- a special case for codec 5, 3840x2160, class 0x17 (4:2:0 at 59.94/50) and descriptors 17/18 — not at our rates.

`build_ogfile_fx6.fx6_match` is this logic in Python; the emulation checks it against the real matcher for every descriptor (+0x88 = 0 and 2).

**Not traced:** the values of request +0x88 / +0x1c the FX6 actually sends (the request is built by the dispatcher 0x20d468/0x20d488 from the IPC
packet; the libmpr EncOpen layout does not map onto it at a fixed offset). The design does not depend on them (next section).

## The design `ogfile2560_xavc_fx6_v1`

| Kind | Sites | What |
|---|---|---|
| L1-comb | 2 | libmpr g_videoParamComb rows 0 and 9 (+6): height 2160 → 2560 (the encoder request) |
| A1-desc | 12 | height +0x80 → 2560 of **every** QFHD descriptor of XAVC-L 4:2:0 8-bit (codec 5, class 0x1a: #0, #19, #53, #54) and XAVC-I (codec 8, classes 0x55 and 0x56: #30, #41, #93, #98, #99, #103, #104, #114) at coding rates 5 (23.98p) and 3 (25p), S&Q rows (input rate 60/120) included |
| A2-profile | 34 | their profiles (each key used by its descriptor only, one profile per key): height +0x06 and +0x38 → 2560; rows for the first core +0x56: 1072 → 1280 where not 0 (all XAVC-I profiles, the two UseCore-2 XAVC-L ones) |
| A3-clip | 1 | clip-format row 1 (8192x4320 code 1; the FX6 records no 8K) → 3840x2560 code 16 |

**Why whole groups, S&Q rows included.** Changing every descriptor of a (codec, rate, class) group keeps their order, and the raster is the only
compared field that changes, so a request at 3840x2560 reaches exactly the descriptor the same request reaches at 3840x2160 on a stock camera,
whatever its +0x88 and input-rate words. Emulated for +0x88 = 0..6 and input rates 0/60/120/−1: 336 requests, all equivalent; 210 requests of
the other XAVC-L/XAVC-I descriptors (other rates and classes, 4:2:2, DCI, HD) give the same answer with and without the design.

**No unit-type site (unlike the FX3's A0).** The memory function 0x201804 (read and emulated): pixels > 8,847,360 → unit type 4 for the intra
codecs {8, 10, 0x18}, type 3 otherwise; S&Q is refused above 995,328,000 pixels a second.
- XAVC-I at 3840x2560 takes type 4, whose row is the 4K row: it asks exactly what it asks stock at 2160 (0x486, 0x474, 0x47a, 0x477, then 0x485).
- XAVC-L at 3840x2560 takes type 3 = (none, LD 0x473, multi 0x476, ES 0x479). **That is the class a stock XAVC-L QFHD S&Q-120 recording already
  uses** (emulated: stock #53/#54 at 2160 and input rate 120 ask 0x473, 0x479, 0x476, 0x485). So no shared row is changed, and stock S&Q keeps
  its blocks. (On the FX3 type 3 had no usable memory; on the FX6 0x473/0x476 have the 4K LD/multi sizes, 0x479 is a 208 MB ES block.)

**Codec memory, with the FX6's own codec firmware** (`Firmware6` in the emulator; self-check: every stock QFHD XAVC-L/XAVC-I descriptor fits):

| Descriptor at 3840x2560 | CD | LD | multi | blocks | fits |
|---|---|---|---|---|---|
| XAVC-I (all 8) | 44,269,568 | 0 | 3,702,784 | CD 0x486 100,794,368; multi 9,502,720 | yes |
| XAVC-L 4:2:0 normal speed (#0, #19) | 2,490,368 | 29,523,968 | 6,225,920 | LD 0x473 33,849,344; multi 0x476 9,502,720; no CD block | yes (stock #53/#54 need CD 4,980,736 on the same class without a CD block) |
| XAVC-L 4:2:2 10-bit (#37–#39, #49–#51) | 2,490,368 | **39,354,368** | **11,141,120** | LD 33,849,344; multi 9,502,720 | **no** → left out |

Stock XAVC-L 4:2:2 10-bit QFHD at 2160 already needs LD 33,193,984 of 33,849,344. The FX3's 0x474/0x477 are 50.8 MB / 14.2 MB, which is why its
XAVC S 4:2:2 works at 2560. A 4:2:2 10-bit XAVC-L open gate would need bigger LD/multi blocks for that request (a DmmCfg design, not attempted).

**While applied (to be said in the README):**
- XAVC-I QFHD and XAVC-L QFHD 4:2:0 8-bit record 3840x2560 at 23.98p and 25p.
- **XAVC-L QFHD 4:2:2 10-bit must not be recorded**: its comb row is unchanged, so its encoder opens for 2,160 rows while the coprocessor
  delivers 2,560 (on the A7 IV the output size alone gave a recording that stopped after about one second, F688).
- The changed formats at 59.94p/50p/29.97p find no descriptor (refused at encoder open, as on the FX3). S&Q at 120 fps is refused by the memory
  function; S&Q up to 60 fps (XAVC-I class 0x56 rows) would encode 3840x2560 of whatever the coprocessor delivers in that mode.
- XAVC-I DCI, HD, MPEG-2, proxies: untouched. Clip-format code of 3840x2560 = 16 (the QFHD code), 4096x2160 still 14.
- The MXF header and Sony's XML still say 3840x2160, 16:9 (the AVC SPS says 3840x2560).

**Guards for the helper** (in the JSON, `suggested_avcam_guards`; none overlaps a site): unit rows 0–6 (0x37815c, 112 bytes), clip rows 2–7
(0x377678, 96), descriptors 1–3 (0x37825c, 432). The FX3 helper's "descriptors 0–3" guard would overlap site #0 here.

## Metadata (the MXF header): v2 BUILT 2026-11-26 (after this section's first version)

The owner asked for it ("Yes, build it"). The path below (format fill → builder → resolution code) turned out not to be the one that writes the
picture descriptor. The descriptor is written by `muxMxfAvcFilePackageSectionPictureDescriptorCreate` (libmpr 0x612dec, `muxMxfAvcFinalize.c`):
- widths and aspect from a switch on the horizontal code [ctx+0x170] (ctx 0x6bdabc8, jump table 0xd728bc): 3840 = code 0x12 (16:9 at
  0x6131e0 / 0x6131e8);
- heights and line map from a switch on the vertical code [ctx+0x174]: 2160 lines = 0xb (0x613388, shared with 4096);
- both codes are copied from the format metadata in `muxMxfAvcNrtMetaInfoGet` (0x60a98c), independent of the comb heights.
Design `ogfile2560_xavc_fx6_v2` = v1 + 4 libmpr code entries (`build/mxf_meta_sites_fx6.py`, `build/build_ogfile_fx6_meta.py`): aspect 3:2 in
the 0x12 case; the 2160-line case rewritten to `ldr w1,[x29,#0x78]; mov w0,#0x870; cmp w1,#0xf00; b.ne; mov w0,#0xa00; str [0x70]; str [0x6c];
b 0x613354` (the 1080p case's tail: line map 42, 0). Emulated (`build/emu_mxf_meta_fx6.py` → `evidence/fx6/mxf_meta_emu_fx6.json`, 30 cases): QFHD
3840x2560 3/2; DCI/2K/HD/720 byte-identical; Sony's own 2048 → 3840 fall-through (codec type ≠ 4; no FX6 XAVC format is 2048 wide) reads 3/2.
Sony's XML is not changed. The rest of this section is the first reading, kept as it was.

### First reading (before v2)

What was found (static):
- **MXF format fill `0x548a3c`** (unexported; called at 0x54825c from a libXavcMxf record-start function at 0x547c08): a switch on the comb index
  (jump table 0xd4e198, 20 entries) fills a 0x154-byte parameter block: +0 compression (7 = AVC long, 6 = AVC intra, 9/10 MPEG-2), +8, +0xc, +0x10,
  **+0x30 width, +0x34 height as code immediates**: comb 0 `mov w1, #0x870` at **0x548abc**, comb 2 at **0x548b54**, comb 9 at **0x548c38** (DCI
  comb 17 at 0x548bec; combs 4–8 go to the error path).
- The block is copied into a builder object (constructor 0x82c9e0, `this+0x11898`, vtable via GOT 0x108eb58); its build 0x82d704 calls ~20
  sub-builders with the block. Width/height are read in four places (0x82d998, 0x82e894, 0x82eb78, 0x82eca8), three of them only to get a
  **resolution code** from `0x82fd3c`, which copies a 15-row {code, w, h} table from .rodata **0xddf450** (its only reference) and returns the code
  of an exact (w, h) match, **default 1**: QFHD is code 15 at 0xddf4ec (height word 0xddf4f4), DCI code 14. Codes 14/15 set `this+0xe4 = 0x2800`
  (other codes 0x1000/0x1200), and code-keyed tables follow (0xddeb70, 0x780 bytes; 0xddf2f0, 0xf0 bytes). 0x82f740(·, ·, class, w, h) only
  special-cases 4096x2160 intra.
- The CDCI descriptor templates in libmpr (.rodata 0xe9afa0/0xe9b468/0xdcdda8, .data 0x1b84c88/0x1b86700) are SD/HD MPEG-2 ones (720/1440/1920);
  no XAVC template holds 3840/2160, so the XAVC header is built at run time by the C muxer (`MuxMxf*`, CFI_PPN_HORIZON/VERTICAL_PIXELS enums).
  An HD/IMX muxer path validates `numOfVerticalLine` against 720/1080 only (0x5dffb0); the XAVC path's checks were not found.

Why no v2: changing only the three immediates would make 3840x2560 fall to resolution code 1 (buffer size 0x1200 instead of 0x2800, other
code-keyed tables): a likely recording failure. Changing the immediates **and** the code-15 height (0xddf4f4) keeps code 15, but where the header's
StoredHeight/SampledHeight/DisplayHeight and the 16:9 AspectRatio come from (the block's +0x34 or a code-15 table) was not followed into the
muxer. Candidate v2 sites, untested: libmpr code 0x548abc and 0x548c38 (`mov w1, #0x870` → `#0xa00`), data 0xddf4f4 (2160 → 2560). Next step if
wanted: emulate the builder 0x82d704 and the muxer's header writer stock vs those sites and look for the 2160s in the output.

## In-camera playback (report only)

The FX6's decode set-up has **the FX3 form for the XAVC codecs**: the channel table 0xb9514c has 8 rows (4096x2160 ×4, 1920x1088, 3840x2160,
8192x4320, 7680x4320); the row choice (code before 0x1fc8a8) takes row 5 for codec 0x13, row 6 for codec 0x12, row 7 when request +0xb0 is 0xe,
otherwise row 0 (4096x2160); the memory ids (0x1fc33c–0x1fc3e4) are the 8K ids 0x47c/0x47e only for codecs 0x12/0x13, else the 4K ids 0x47d/0x47f.
So an XAVC-I/L clip of 3840x2560 (over 2160 rows and 8,847,360 pixels) is expected to fail to play on the camera, as on the FX3 before its P29
step. A fix in the FX3's spirit would send the XAVC codecs down the 8K branch (row 6 + 0x47c/0x47e); not designed. Testers: don't play back.

## Observed vs inferred, and risks

- Observed (code/data read, emulated): every table and function address above; the matcher, memory function, start-block builder and clip function
  run on the FX6's own code; the codec need on the FX6's own codec firmware; SetEncOpenParam's copy and relocation.
- Inferred: which comb row each menu format uses (from the rows' fields, m_vpcSt and the MXF format fill; the menu → comb mapping in appFw was not
  traced); that type 3 without a CD block works at normal speed for XAVC-L 4:2:0 (it works for Sony's own S&Q 120, which needs more CD).
- Risks for the camera: that the codec and the MXF muxer accept a 2,560-row AVC stream in a 2,160-row container (they do on the FX3 in MP4); the
  level label (5.1/5.2 below 38,400 macroblocks, as on the FX3); MXF index/CBR handling for XAVC-I with a bigger picture at the same per-frame budget
  (the budget +0x5c is kept: 0.84× the bits per pixel); the S&Q-60 XAVC-I rows; XAVC-L 4:2:2 10-bit recorded by mistake while applied.
- Trace helpers used: `evidence/fx6/encoder_trace_2026-11-26/` (format-fill decoder, playback-form scan, xref/BL scanners).
