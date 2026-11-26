# FX6 open gate: test kit (firmware 6.02)

<p><b>Open gate records on an FX6.</b> With the memory step a tester found, an FX6 on firmware 6.02 recorded clean 3840 × 2560 XAVC-I clips of the whole sensor area at 23.98p (issue 2, 2026-11-26). This kit is the FX3 open-gate kit ported to the Sony FX6 (ILME-FX6). The patch only writes to the camera's memory. Not right yet: an error code (E95-311) that comes with the sensor step, XAVC-L, and the LCD step.</p>

**Where it stands (2026-11-26, second kit; updated after the alt-memory run in issue 1):**

- **What two testers showed** (issues 1 and 2):
  - The sensor step works: the sensor runs its full height.
  - The FX6 needs a **memory step** the FX3 does not. Its output picture buffers hold 3840 × 2304. Without the step, clips were not written and USB locked up (issue 1), or the last 256 rows repeated the top of the picture (issue 2). [@Mininoob](https://github.com/Mininoob) found the cause and the fix and ran it; it is now the first step of the apply. [@isaiahoadeoye-star](https://github.com/isaiahoadeoye-star) narrowed the fault to the output-size step.
  - With the memory step first, XAVC-I QFHD 23.98p recorded 3840 × 2560 with real picture in every row, and the MXF header says 3840 × 2560, 3:2.
- **The order changed.** The first kit applied the output size before its buffers and its encoder were ready. Now: memory, sensor, encoder, output size.
- **The LCD step is off by default.** On both cameras it gave a broken preview (jitter; the picture in three sections). Without it the LCD shows the whole 3:2 picture stretched sideways to fill the 16:9 panel: fine for framing, wrong for shapes. The file is not stretched. `open_gate_apply_with_screen.cmd` still applies it, for testing.
- **E95-311 comes with the sensor step.** It shows as `E95-311` with beeps and a blinking record lamp, and stays until power-off.
  - Tester 2 (XAVC-I): straight after the sensor step, with a black picture until the next step. The camera then recorded clean 3840 × 2560 clips all the same.
  - Tester 1 (XAVC-L): with the sensor step alone (no memory step, 2160-row output), a clean squeezed clip, then E95-311 after about 10 seconds of recording. With the full apply and the memory variant: after the last step.
  - So it is not the memory step. `open_gate_apply_alt_memory.cmd` was built to test that idea and did not avoid it.
  - The FX6's own firmware never runs the sensor's full-height mode: on the FX3 and A7S III a stills mode uses it, and the FX6 has no stills. What the FX6 checks and reports as E95-311 is not known yet.
- **XAVC-L crashed.** Tester 1's full apply with XAVC-L 4:2:0 8-bit (memory variant): every step done, E95-311, then pressing REC crashed the camera and no clip was written. **Record XAVC-I.** Whether XAVC-L itself is the cause (rather than that camera or the variant) is not known yet.
- **Not yet run:** this exact order with the default memory step and without the LCD step; 25p.
- **Formats:** XAVC-I QFHD at **23.98p** (the encoder step also covers XAVC-L QFHD **4:2:0 8-bit**, which crashed once, see above). **Not XAVC-L 4:2:2 10-bit**: at 3840 × 2560 its encoder needs more memory than the FX6 gives it, so it is left unchanged; do not record it while the kit is applied. **Not 25p**: the sensor step changes the 23.98p video mode only.
- **File headers.** The encoder step makes the MXF header's picture descriptor say 3840 × 2560 and 3:2, so editors should open the files at 3:2 (confirmed on the tester's clip). Sony's XML (in the file and the M01.XML sidecar) still says 3840 × 2160, 16:9. `open_gate_apply_no_meta.cmd` leaves the MXF header at 3840 × 2160.
- **The debug dump.** `dump_info.cmd` (and the last session of the apply) writes a read-only report of the camera's state: the video mode it ran, the sensor registers, the scaler, the output-buffer memory table, the LCD's panel type, the camera's log files and the patch sites. Please send it with every report.
- **A power-off probably removes the patch** (it does on the A7S III): apply it again after every power-on.

**What it does.** FF, QFHD 3840 × 2160 at 23.98p in XAVC-I becomes a 3840 × 2560 (3:2) recording of the whole sensor height, set in the camera's memory only. A battery pull removes it.

| Launcher | What it does | Writes to the camera? |
|---|---|---|
| `check_readonly.cmd` | Confirms the camera runs the 6.02 software the port was made from and reads what every patch site holds. Verdict READY / NOT READY | No |
| `dump_info.cmd` | **The debug dump:** the same, plus the memory map, the camera's own logs, sensor register state, scaler state, the output-buffer table, the video mode it last ran, and the LCD's panel type and words | No |
| `open_gate_apply.cmd` | Applies the open-gate state in four steps (memory, sensor, encoder, output size), then takes the debug dump | **Yes: memory only** |
| `open_gate_apply_alt_memory.cmd` | **Test.** The same with the memory step's variant. Ran once (XAVC-L): E95-311, then a crash on REC | **Yes: memory only** |
| `open_gate_apply_with_screen.cmd` | **Test.** The four steps plus the LCD step, which gave a broken preview on two FX6s | **Yes: memory only** |
| `open_gate_apply_no_meta.cmd` | The four steps with the encoder step that leaves the MXF header at 3840 × 2160, 16:9 | **Yes: memory only** |
| `open_gate_putback.cmd` | Puts every step back (five sessions; it also removes the LCD step and either memory variant) | Yes: memory only |
| `screen_putback.cmd` | Puts back only the LCD step | Yes: memory only |

Nothing in this kit writes to the camera's firmware or to its settings.

## Before you start

1. The camera's menu (Maintenance > Version) must show **6.02**. On any other version, stop and tell us the version.
2. **Imager Scan Mode FF**, Rec Format **3840 × 2160 (QFHD)**, frame rate **23.98p**, codec **XAVC-I** (XAVC-L 4:2:0 8-bit crashed on one FX6 with this kit; never XAVC-L 4:2:2 10-bit). S&Q Motion off, Proxy Rec off. Other settings use video modes this kit does not change.
3. A charged battery or the AC adaptor. Do not record or play back while a step runs.
4. **USB:** connect the camera to the computer with a USB cable. When the camera asks **"Connect USB Now?"**, choose **Execute** (Mass Storage). If USB Streaming or USB Tethering is on, turn it off first.
5. If you used the first kit: pull the battery for 10 seconds first, and run `check_readonly.cmd` again. The new apply needs a check made with this kit.

## Windows, once

1. Install Python 3.10 or later from python.org (with the "py launcher").
2. Run `windows/setup.cmd`.
3. Install the libusb-win32 driver for the camera with [Zadig](https://zadig.akeo.ie): Options, List All Devices, pick the camera, choose libusb-win32, Replace Driver. The first run switches the camera to service mode, where it shows up as a new device: install the driver for that one too, then run the step again.

## macOS, once

The macOS kit is the A7 IV kit's macOS port, the same as in the FX3 kit apart from the launcher names. It runs the same scripts as Windows (`windows/tools`). The first FX6 run of this kit was on a Mac.

1. Python 3.9 or later: the one macOS offers with the Xcode Command Line Tools (run `xcode-select --install` in Terminal) works, or install it from python.org.
2. Double-click `macos/setup.command`. It sets up Python and the USB library the scripts use. No Homebrew and no driver are needed.
3. Each Windows launcher has a macOS twin with the same name and `.command` instead of `.cmd`. Everything below that says `.cmd` works the same with the `.command` file.

If a launcher stops with `run.sh: Permission denied`, run `chmod +x macos/run.sh macos/*.command` in Terminal once (issue 1).

Each live run asks for your Mac password: macOS keeps its own driver on the camera's USB connection, and only an administrator can hand the camera over to the script. The script unmounts the camera's memory card first; it does not erase anything on it. The results go to the same `windows/camera_private` folder.

If macOS refuses to open a .command file ("unidentified developer" or "could not verify"), open System Settings > Privacy & Security, scroll down and click "Open Anyway". Or open Terminal, type `bash` and a space, drag the .command file into the window, and press Return.

## Android (the app has not run on a phone with an FX6 yet)

`android/FX6-OpenGate.apk` (0.2) runs this kit from a phone connected to the camera by USB (with an OTG adapter or cable if needed). It carries exactly the files in `windows/tools` of this commit and runs them unchanged; only the USB access, the dialogs and the folder for the results are the phone's.

1. Install the APK (allow installing from unknown sources). It installs beside the FX3, A7 IV and A7S III apps; they do not share anything on the phone.
2. Set the camera as for the PC (above).
3. **1. Read-only check** first: the apply starts only after a check on this phone said READY. Then **2. Apply to camera**. Leave the "LCD step" box unticked to record; ticked, the LCD step is added (test). The app has no button for the memory variant.
4. When Android asks to open *FX6 Open Gate* for the camera, tick **Always** and press OK. It comes up twice: once in Mass Storage, once in service mode.
5. When the log says **unplug and plug in again**, do that with the phone cable (and choose Execute on the camera). Never switch the camera off.
6. **Stop waiting** ends a wait for the camera. It never interrupts a step that is talking to the camera.
7. **Dump info** takes the debug dump. Afterwards, **Export logs** writes a zip to `Download/FX6-OpenGate/` on the phone: send that zip back.

**Self-test** and **Dry run** need no camera and send nothing.

## The read-only steps

Each launcher asks for the firmware version the menu shows. Each run makes a new folder in `windows/camera_private`.

- **Check:** camera set as above, connect, run `check_readonly.cmd`. It must say VERDICT READY before an apply.
- **Debug dump of the stock camera** (please send one before the first apply): camera set as above (FF, QFHD 23.98p), record a few seconds, stop, connect, run `dump_info.cmd`. It records which video mode the camera ran (the kit changes mode 0x8c0), the output-buffer table and the LCD's panel type.

What they do to the camera: they switch it to service mode, write one small program file to the service partition, which the camera loads once, and delete that file again in the same session. The program only reads and creates one file, its report, on the camera's RAM disk. Its source is `windows/tools/camera_tests/CT6_memory_read_check/helper_fx6/fx6read.c`.

## The write steps

**What they change.** Groups of bytes in the running camera's memory, one per step, in this order:

1. **Memory** (found and first run by [@Mininoob](https://github.com/Mininoob), issue 2; 10 words). The FX6 keeps its output pictures in buffers of 13,271,040 bytes at 1.5 bytes per pixel, which is 3840 × 2304. A 2560-row picture needs 14,745,600. Eight bigger buffers do not fit their block, so seven get the bigger size and the eighth is taken out of use. The words are in the camera's working copy of its memory table, which it rebuilds from its own file at every start.
   - `open_gate_apply.cmd` writes the tester's ten words. They also enlarge the one such buffer of another layout, which then no longer fits its block; in emulation the memory manager refuses the first request that reaches it.
   - `open_gate_apply_alt_memory.cmd` takes that buffer out of use instead. In emulation there is no refusal and no layout over its block. It ran once (issue 1, XAVC-L): every step done, then E95-311 and a crash on REC.
2. **Sensor** (the FX3's step): the sensor read-out and the two 4K picture records of the image processor take the full sensor height instead of the 16:9 band. Runs on both testers' cameras.
3. **Encoder** (made for the FX6; 53 sites): the encoder request's height for XAVC-I QFHD and XAVC-L QFHD 4:2:0 8-bit (2160 → 2560), the encoder's entries for those formats with their profiles, and the label the outputs get for the recording; and in the MXF header writer, a QFHD clip's picture height (2560) and aspect ratio (3:2), with DCI 4K kept at 4096 × 2160. XAVC-L 4:2:2 10-bit, DCI 4K, HD and proxies are not touched.
4. **Output size** (the FX3's step; one word): 3840 × 2160 becomes 3840 × 2560. It is last because it needs the buffers of step 1 and the encoder of step 3.
5. **LCD** (only with `open_gate_apply_with_screen.cmd`; 8 words): meant to show the picture at its true 3:2 shape with black bars left and right on the 16:9 LCD. On two FX6s it gave a broken preview instead. It does not affect the recording.

Each step first checks that every byte it is about to change holds its stock value and that the bytes around them are the expected ones, writes, reads back, and undoes its own writes if anything does not match. Running the apply again in the same power-on is fine: steps whose bytes are already in place say NOTHING TO DO.

**How to run it**

1. Set the camera as in "Before you start". LCD Monitor De-Squeeze off.
2. Pull the battery for 10 seconds and switch on, so that nothing of an earlier run is left.
3. Connect USB (Execute) and run `windows/check_readonly.cmd`. It must say VERDICT READY.
4. Run `windows/open_gate_apply.cmd`. It starts only if your newest saved check or dump says READY. It asks for the firmware version and for a typed YES.
5. It runs four steps. Between steps it asks you to **unplug and replug the USB cable** (choose Execute each time). **Do not switch the camera off and do not pull the battery** until the script says it is finished: either one removes what was applied.
6. **From the sensor step (step 2) on, E95-311 may appear** with beeps and a blinking record lamp, at once (the picture may go black until the next step) or later. Carry on with the next step; do not pull the battery. Note when it appeared and which Rec Format was set.
7. After the four steps the script asks for one more session, which only reads: **unplug, look at the LCD for five seconds, plug in again.** **Do not press REC before this session has finished**, even if an error code is showing: on one FX6, REC then crashed the camera and no dump of the applied state could be taken. It then takes the debug dump by itself and says whether the sensor ran the open-gate mode.
8. When it says so, unplug. The LCD shows the whole picture stretched sideways.
9. Record 20 to 30 seconds and stop. **Do not play it back on the camera** (see below): check it on a computer.
10. To return to stock: battery out for 10 seconds, or `open_gate_putback.cmd`.

**While it is applied**

- Use only **FF, QFHD 3840 × 2160, 23.98p, XAVC-I**. Other frame rates run video modes this kit does not change: on the A7S III 60p distorted the picture and crashed the camera, and 25p on these cameras runs a mode that shares the patched picture records without the sensor change. S35 and DCI 4K stay 16:9; S35 QFHD would come out stretched.
- **Switch the camera off (battery out for 10 seconds) before using HD, DCI 4K or S&Q.** The memory step leaves 14 output buffers instead of 17 and has only been run in QFHD. With the tester's ten words one layout no longer fits its block, and the tester expects an `EA0-000` error in a mode that needs it.
- **Do not record XAVC-L 4:2:2 10-bit** while it is applied: its encoder is still opened for 2160 rows while the picture has 2560 (on the A7 IV that stopped a recording after about a second).
- **Do not play clips back on the camera.** On two FX3s an open-gate clip would not play and a second try froze the camera until the battery was pulled. The FX6 opens its XAVC playback decoder at 4096 × 2160 the way the FX3 does, so a 3840 × 2560 clip is expected to fail the same way.
- If E95-311 is on the screen, the camera beeps and the lamp blinks until it is switched off. Tester 2's camera recorded XAVC-I all the same; tester 1's crashed on REC with XAVC-L.
- **Do not switch the camera off:** on the A7S III the power switch removes the patch. Assume it does here too.

**Please send back**

- The zipped `windows/camera_private` folder, with the debug dump the apply ends with (and a stock dump from before, if you took one).
- **Whether E95-311 (or any code) appeared, when (after which step, or how long into a recording), and your Rec Format.**
- What the LCD showed after the apply. With `open_gate_apply_with_screen`: a phone photo of the LCD, and what an SDI or HDMI monitor shows if one is connected.
- The clip, or what MediaInfo says about it: `mediainfo --Output="Video;%Width%x%Height% original %Width_Original%x%Height_Original% %DisplayAspectRatio/String% %Format% %Format_Profile% %BitRate%" FILE` (expected: 3840x2560 with no "original" size and 3:2). Whether the picture is the whole 3:2 sensor area and clean down to the last row in every frame, whether it recorded to the end, and how your editor opens it. 
- Your settings: Imager Scan Mode, Rec Format (codec and quality), frame rate, NTSC/PAL area, Shooting Mode (Custom or Cine EI), base ISO.
- **One check after a power-off** when you are done: switch the camera off and on with the power switch (no battery pull), run `check_readonly.cmd`, and include that folder. It tells us whether the power switch removes the patch on the FX6.

**If the camera misbehaves** (grey lines, purple picture, flicker, restart, freeze, recording that stops by itself, no clip on the card): if the camera still responds, connect USB, run `dump_info.cmd` first, and send the folder; then pull the battery for 10 seconds. If it does not respond, just pull the battery.

**If the apply stops part-way:** it says at which step and why. Pull the battery for 10 seconds to be sure of the camera's state, and send the folder. If the memory step says NOTHING WRITTEN, the camera's memory table is not what the kit expects: nothing was changed; please send the folder.

## If something stops

Every stop prints a reason and "Nothing was sent" or what was sent. Please send that text. Common ones:

- *the camera is in service mode but that device has no libusb driver yet*: expected on the first run. Do the Zadig step for the new device and run again.
- *DeviceInfo.xml is not the file of the 6.02 update*: another firmware or model. Nothing further is sent.
- *DIFFERS from the 6.02 update* in a check: not an FX6 on 6.02 (an FX3 gives this too). The apply will not start.
- *The newest saved read-only check ... does not say READY*: run `check_readonly.cmd` with this kit first.
- *a libJit.so is already on the service partition*: an earlier session was cut off. If the file is one of this kit's, the next run deletes it by itself and goes on. If it is not, the message gives its SHA-256 and how to delete it.

## What is in here

- `windows/`: the launchers, `setup.cmd`, and `tools/`:
  - the scripts, the pinned program files and their source;
  - the patch designs of every step;
  - the builders and emulations of the designs (`tools/modding/fx6`).
- `macos/`: `setup.command` and one `.command` launcher per Windows launcher; they run `windows/tools`.
- `android/FX6-OpenGate.apk`: the phone app, carrying `windows/tools` as published here.
- `PORT_NOTES.md`: how the FX3 kit maps onto the FX6, what was checked and how, what the testers found, and what is not known.

Built on [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE) (vendored under `windows/tools/third_party`, MIT licence). The memory step is [@Mininoob](https://github.com/Mininoob)'s work (issue 2).
