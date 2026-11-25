# FX6 open gate: test kit (firmware 6.02)

<p><b>NOT YET RUN ON AN FX6.</b> This kit is the FX3 open-gate kit (which works on two FX3s, 2026-11-24) ported to the Sony FX6 (ILME-FX6) firmware 6.02. It is meant to record a true 3840 × 2560 picture of the whole sensor area at 23.98p, and to show it at 3:2 on the FX6's LCD. The patch only writes to the camera's memory.</p>

**Where it stands (2026-11-26):**

- **Built and checked in emulation only.** Every step was run against the FX6's own code in an emulator, and the program files the camera loads were run against a model FX6. Nobody has run it on an FX6 yet: the first testers' results decide whether it works.
- **Why it should work.** The FX6's image processor carries the FX3's sensor code and tables: the same sensor, the same 40 video modes in the same order, every sensor table byte for byte, the same record calculator, scaler and size table. The sensor and size steps are the FX3's working steps at the FX6's addresses.
- **What is new for the FX6:** the encoder step (the FX6 records XAVC-I and XAVC-L in MXF files, not XAVC HS/S in MP4) and the LCD step (the FX6's LCD is 16:9). Both were made for the FX6 and are the least proven parts. See `PORT_NOTES.md`.
- **Formats:** XAVC-I QFHD and XAVC-L QFHD **4:2:0 8-bit** at 23.98p. **Not XAVC-L 4:2:2 10-bit**: at 3840 × 2560 its encoder needs more memory than the FX6 gives it, so it is left unchanged; do not record it while the kit is applied.
- **File headers (the FX3 kit's metadata fix, for MXF).** The encoder step also makes the MXF header's picture descriptor say 3840 × 2560 (stored, sampled and display height) and a 3:2 aspect ratio, so editors should open the files at 3:2. This was checked by running the FX6's own MXF header writer in an emulator: QFHD gets 3840 × 2560 and 3:2, DCI 4K, HD and 720 headers stay byte for byte as stock. Sony's XML (in the file and the M01.XML sidecar) still says 3840 × 2160, 16:9, as on the FX3. `open_gate_apply_no_meta.cmd` leaves the MXF header at 3840 × 2160.
- **The debug dump.** `dump_info.cmd` (and the last session of the apply) writes a read-only report of the camera's state: the video mode it ran, the sensor registers, the scaler, the LCD's panel type and the patch sites. Please send it with every report.
- **A power-off probably removes the patch** (it does on the A7S III): apply it again after every power-on.

**What it does.** FF, QFHD 3840 × 2160 at 23.98p in XAVC-I or XAVC-L 4:2:0 8-bit becomes a 3840 × 2560 (3:2) recording of the whole sensor height, set in the camera's memory only. A battery pull removes it.

| Launcher | What it does | Writes to the camera? |
|---|---|---|
| `check_readonly.cmd` | Confirms the camera runs the 6.02 software the port was made from and reads what every patch site holds. Verdict READY / NOT READY | No |
| `dump_info.cmd` | **The debug dump:** the same, plus the memory map, the camera's own logs, sensor register state, scaler state, the video mode it last ran, and the LCD's panel type and words | No |
| `open_gate_apply.cmd` | Applies the open-gate state in four steps (sensor, size, encoder, LCD), then takes the debug dump | **Yes: memory only** |
| `open_gate_apply_no_screen.cmd` | Only the three open-gate steps (the LCD keeps its stock 16:9 view) | **Yes: memory only** |
| `open_gate_apply_no_meta.cmd` | The four steps with the encoder step that leaves the MXF header at 3840 × 2160, 16:9 | **Yes: memory only** |
| `open_gate_putback.cmd` | Puts every step back | Yes: memory only |
| `screen_putback.cmd` | Puts back only the LCD step | Yes: memory only |

Nothing in this kit writes to the camera's firmware or to its settings.

## Before you start

1. The camera's menu (Maintenance > Version) must show **6.02**. On any other version, stop and tell us the version.
2. **Imager Scan Mode FF**, Rec Format **3840 × 2160 (QFHD)**, frame rate **23.98p**, codec **XAVC-I** or **XAVC-L 4:2:0 8-bit** (not XAVC-L 4:2:2 10-bit). S&Q Motion off, Proxy Rec off. Other settings use video modes this kit does not change.
3. A charged battery or the AC adaptor. Do not record or play back while a step runs.
4. **USB:** connect the camera to the computer with a USB cable. When the camera asks **"Connect USB Now?"**, choose **Execute** (Mass Storage). If USB Streaming or USB Tethering is on, turn it off first.

## Windows, once

1. Install Python 3.10 or later from python.org (with the "py launcher").
2. Run `windows/setup.cmd`.
3. Install the libusb-win32 driver for the camera with [Zadig](https://zadig.akeo.ie): Options, List All Devices, pick the camera, choose libusb-win32, Replace Driver. The first run switches the camera to service mode, where it shows up as a new device: install the driver for that one too, then run the step again.

## macOS, once (not run with an FX6 yet)

The macOS kit is the A7 IV kit's macOS port, the same as in the FX3 kit apart from the launcher names. It runs the same scripts as Windows (`windows/tools`).

1. Python 3.9 or later: the one macOS offers with the Xcode Command Line Tools (run `xcode-select --install` in Terminal) works, or install it from python.org.
2. Double-click `macos/setup.command`. It sets up Python and the USB library the scripts use. No Homebrew and no driver are needed.
3. Each Windows launcher has a macOS twin with the same name: `macos/check_readonly.command`, `dump_info.command`, `open_gate_apply.command`, `open_gate_apply_no_screen.command`, `open_gate_apply_no_meta.command`, `open_gate_putback.command`, `screen_putback.command`. Everything below that says `.cmd` works the same with the `.command` file.

Each live run asks for your Mac password: macOS keeps its own driver on the camera's USB connection, and only an administrator can hand the camera over to the script. The script unmounts the camera's memory card first; it does not erase anything on it. The results go to the same `windows/camera_private` folder.

If macOS refuses to open a .command file ("unidentified developer" or "could not verify"), open System Settings > Privacy & Security, scroll down and click "Open Anyway". Or open Terminal, type `bash` and a space, drag the .command file into the window, and press Return.

## Android (not run on a phone or camera yet)

`android/FX6-OpenGate.apk` runs this kit from a phone connected to the camera by USB (with an OTG adapter or cable if needed). It carries exactly the files in `windows/tools` of this commit and runs them unchanged; only the USB access, the dialogs and the folder for the results are the phone's.

1. Install the APK (allow installing from unknown sources). It installs beside the FX3, A7 IV and A7S III apps; they do not share anything on the phone.
2. Set the camera as for the PC (above).
3. **1. Read-only check** first: the apply starts only after a check on this phone said READY. Then **2. Apply to camera**. The "LCD step" box chooses between the four-step apply (ticked) and the three open-gate steps only.
4. When Android asks to open *FX6 Open Gate* for the camera, tick **Always** and press OK. It comes up twice: once in Mass Storage, once in service mode.
5. When the log says **unplug and plug in again**, do that with the phone cable (and choose Execute on the camera). Never switch the camera off.
6. **Stop waiting** ends a wait for the camera. It never interrupts a step that is talking to the camera.
7. **Dump info** takes the debug dump. Afterwards, **Export logs** writes a zip to `Download/FX6-OpenGate/` on the phone: send that zip back.

**Self-test** and **Dry run** need no camera and send nothing.

## The read-only steps

Each launcher asks for the firmware version the menu shows. Each run makes a new folder in `windows/camera_private`.

- **Check:** camera set as above, connect, run `check_readonly.cmd`. It must say VERDICT READY before an apply.
- **Debug dump of the stock camera** (please send one before the first apply): camera set as above (FF, QFHD 23.98p), record a few seconds, stop, connect, run `dump_info.cmd`. It records which video mode the camera ran (the kit changes mode 0x8c0) and the LCD's panel type.

What they do to the camera: they switch it to service mode, write one small program file to the service partition, which the camera loads once, and delete that file again in the same session. The program only reads and creates one file, its report, on the camera's RAM disk. Its source is `windows/tools/camera_tests/CT6_memory_read_check/helper_fx6/fx6read.c`.

## The write steps

**What they change.** Four groups of bytes in the running camera's memory, one per step:

1. **Sensor** (the FX3's step, which works on the FX3): the sensor read-out and the two 4K picture records of the image processor take the full sensor height instead of the 16:9 band.
2. **Size:** one word, 3840 × 2160 becomes 3840 × 2560 (the FX3's step).
3. **Encoder** (made for the FX6; 49 sites): the encoder request's height for XAVC-I QFHD and XAVC-L QFHD 4:2:0 8-bit (2160 → 2560), the encoder's entries for those formats at 23.98p and 25p with their profiles (height 2560; the rows the first of the two encoder cores takes, 1072 → 1280), and the label the outputs get for the recording; and in the MXF header writer, a QFHD clip's picture height (2560) and aspect ratio (3:2), with DCI 4K kept at 4096 × 2160 (four code entries). No memory change is needed: XAVC-I at 3840 × 2560 asks the same memory as stock, and XAVC-L 4:2:0 takes the blocks the FX6's own QFHD 120 fps slow motion uses (checked with the FX6's codec firmware's own calculation). XAVC-L 4:2:2 10-bit, DCI 4K, HD and proxies are not touched.
4. **LCD** (made for the FX6; 8 words): the FX6's LCD is 16:9, and the live view is a 16:9 frame holding the whole 3:2 sensor area. Stock FX6 fills the panel with it (squeezed). The step makes the camera show it at its true 3:2 shape: on the 1280 × 720 panel a 1080 × 720 picture with 100-pixel black bars left and right. It also sets the LCD Monitor De-Squeeze shapes for the 3:2 picture: 1.3x shows 1.95:1, 2.0x shows the whole frame at 3:1 (the stock centre crop is turned off).

Each step first checks that every byte it is about to change holds its stock value, writes, reads back, and undoes its own writes if anything does not match. Running the apply again in the same power-on is fine: steps whose bytes are already in place say NOTHING TO DO.

**How to run it**

1. Set the camera as in "Before you start". LCD Monitor De-Squeeze off for now.
2. Optional but helpful: pull the battery for 10 seconds and switch on, so that nothing of an earlier run is left.
3. Connect USB (Execute) and run `windows/check_readonly.cmd`. It must say VERDICT READY.
4. Run `windows/open_gate_apply.cmd`. It starts only if your newest saved check or dump says READY. It asks for the firmware version and for a typed YES.
5. It runs four steps. Between steps it asks you to **unplug and replug the USB cable** (choose Execute each time). **Do not switch the camera off and do not pull the battery** until the script says it is finished: either one removes what was applied.
6. After the four steps the script asks for one more session, which only reads: **unplug, look at the LCD for five seconds, plug in again.** It then takes the debug dump by itself and says whether the sensor ran the open-gate mode.
7. When it says so, unplug. The LCD should show the whole picture at 3:2 with black bars left and right.
8. Record 20 to 30 seconds and stop. **Do not play it back on the camera** (see below): check it on a computer.
9. To return to stock: battery out for 10 seconds, or `open_gate_putback.cmd`.

**While it is applied**

- Use only **FF, QFHD 3840 × 2160, 23.98p, XAVC-I or XAVC-L 4:2:0 8-bit**. Other frame rates run video modes this kit does not change: on the A7S III 60p distorted the picture and crashed the camera, and 25p on these cameras runs a mode that shares the patched picture records without the sensor change. QFHD at 29.97p, 50p and 59.94p finds no encoder entry and will not record. S35 and DCI 4K stay 16:9; S35 QFHD would come out stretched.
- **Do not record XAVC-L 4:2:2 10-bit** while it is applied: its encoder is still opened for 2160 rows while the picture has 2560 (on the A7 IV that stopped a recording after about a second).
- **Do not play clips back on the camera.** On two FX3s an open-gate clip would not play and a second try froze the camera until the battery was pulled. The FX6 opens its XAVC playback decoder at 4096 × 2160 the way the FX3 does, so a 3840 × 2560 clip is expected to fail the same way.
- With the LCD step: every 16:9 picture on the LCD takes the 3:2 shape (other formats look wrong on the LCD), a DCI 17:9 picture fills the LCD, and the de-squeeze shapes are the 3:2 picture's on every output that de-squeezes. SDI and HDMI keep their stock framing on a 16:9 output.
- **Do not switch the camera off:** on the A7S III the power switch removes the patch. Assume it does here too.

**Please send back**

- The zipped `windows/camera_private` folder, with the debug dump the apply ends with (and a stock dump from before, if you took one).
- What the LCD showed after the apply, a phone photo with something round in the picture helps.
- The clip, or what MediaInfo says about it: `mediainfo --Output="Video;%Width%x%Height% original %Width_Original%x%Height_Original% %DisplayAspectRatio/String% %Format% %Format_Profile% %BitRate%" FILE` (expected: 3840x2560 with no "original" size and 3:2; with `open_gate_apply_no_meta` the header says 3840x2160 and the stream 3840x2560). ffprobe cannot show the header change: it reads the size from the stream. Whether the picture is the whole 3:2 sensor area (compare with the same scene in stock QFHD), whether it recorded to the end, and how your editor opens it.
- Your settings: Imager Scan Mode, Rec Format (codec and quality), frame rate, NTSC/PAL area, Shooting Mode (Custom or Cine EI), base ISO.
- **One check after a power-off** when you are done: switch the camera off and on with the power switch (no battery pull), run `check_readonly.cmd`, and include that folder. It tells us whether the power switch removes the patch on the FX6.

**If the camera misbehaves** (grey lines, purple picture, flicker, restart, freeze, recording that stops by itself): if the camera still responds, connect USB, run `dump_info.cmd` first, and send the folder; then pull the battery for 10 seconds. If it does not respond, just pull the battery. `open_gate_apply_no_screen.cmd` applies open gate without the LCD step.

**If the apply stops part-way:** it says at which step. Pull the battery for 10 seconds to be sure of the camera's state, and send the folder.

## If something stops

Every stop prints a reason and "Nothing was sent" or what was sent. Please send that text. Common ones:

- *the camera is in service mode but that device has no libusb driver yet*: expected on the first run. Do the Zadig step for the new device and run again.
- *DeviceInfo.xml is not the file of the 6.02 update*: another firmware or model. Nothing further is sent.
- *DIFFERS from the 6.02 update* in a check: not an FX6 on 6.02 (an FX3 gives this too). The apply will not start.
- *a libJit.so is already on the service partition*: a session broke half-way. Replug, and run the same step with `--remove-only`.

## What is in here

- `windows/`: the launchers, `setup.cmd`, and `tools/`:
  - the scripts, the pinned program files and their source;
  - the patch designs of every step;
  - the builders and emulations of the designs (`tools/modding/fx6`).
- `macos/`: `setup.command` and one `.command` launcher per Windows launcher; they run `windows/tools`.
- `android/FX6-OpenGate.apk`: the phone app, carrying `windows/tools` as published here.
- `PORT_NOTES.md`: how the FX3 kit maps onto the FX6, what was checked and how, and what is not known.

Built on [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE) (vendored under `windows/tools/third_party`, MIT licence).
