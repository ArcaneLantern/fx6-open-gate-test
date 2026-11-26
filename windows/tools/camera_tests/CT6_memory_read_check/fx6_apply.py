"""FX6 (ILME-FX6) firmware 6.02: apply, or put back, the open-gate state in the camera's MEMORY.

  python fx6_apply.py apply    [--screen] [--alt-memory] [--no-meta] [--dry-run] [--no-movie-session]
  python fx6_apply.py putback  [--no-screen] [--dry-run]
  python fx6_apply.py screen | screen-putback  [--dry-run]

The FX6 counterpart of fx3_apply.py: the FX3's open-gate state (which records a true 3840x2560 file of the whole sensor area on two
FX3s, 2026-11-24) ported to the FX6 6.02. The FX6's coprocessor software carries the FX3's imager code and tables at other addresses;
every design here is the FX3's (sensor and output size) or its FX6 counterpart (encoder, screen), checked against the FX6's own code in
emulation (modding/FX6_PORT.md).

RUN ON TWO FX6s (2026-11-25/26, repo issues 1 and 2). What they showed, and what changed here on 2026-11-26:
- The FX6 needs a memory step the FX3 does not: its output planes hold 3840 x 2304 (13,271,040 bytes at 1.5 bytes per pixel). Without it
  the output-size step stopped clips being written and locked USB (issue 1), or the last 256 rows repeated the top (issue 2). A tester
  found the fix and ran it: ten words of the camera's DmmCfg table (issue 2, Mininoob). It is step D16 here, and it goes first.
- With D16 first, then L5, L19, S16, L16, that FX6 recorded clean 3840x2560 XAVC-I 23.98p clips. The MXF header reads 3840x2560, 3:2.
- The LCD step S16 gave a broken preview on both cameras (jitter; the picture in three sections). It is now left out unless --screen is
  given. Without it the LCD shows the 3:2 picture stretched to 16:9: usable for framing, not for judging shapes.
- After L5 one FX6 (XAVC-I) showed E95-311, a black picture, beeps and a blinking record lamp; the picture came back after the next
  step, the code stayed on the screen. The other (XAVC-L) showed no error after L5. The cause is not known.

  apply    four steps, each its own USB session:
             D16  output-plane memory (dmm7slot_fx6_v1; --alt-memory: R16, dmm7slot_fx6_v2, a variant that has not run on a camera)
             L5   sensor side (ogsq_fx6_v1)
             L19  encoder side (ogfile2560_xavc_fx6_v2: XAVC-I QFHD and XAVC-L QFHD 4:2:0 8-bit at 23.98p / 25p record 3840x2560 and the MXF
                  picture descriptor says 3840x2560, 3:2; NOT XAVC-L 4:2:2 10-bit. --no-meta: N19, the header keeps 3840x2160, 16:9)
             L16  output size (outsz2560_fx6_v1). Last: it needs the planes of D16 and the encoder of L19.
           --screen adds S16 (the LCD words) after them. Then one read-only session (the debug dump) after the picture has restarted.
           A step that finds its bytes already applied says NOTHING TO DO and counts as passed.
  putback  the reverse: S17, L17, L20, L6, D17 (--no-screen leaves out S17; on a camera without the screen step S17 says NOTHING TO DO).
           D17 puts back either memory variant. A cold boot (battery out for 10 seconds) also undoes everything.
  screen / screen-putback   only the screen step (S16) or its put back (S17).

The FX6 has no stills mode. During every USB session the camera's picture is stopped (on the A7S III and FX3, whose coprocessor
software this is, the sensor sleeps during a session and the picture is started afresh when it ends), so each step writes while the
picture is stopped, and the next unplug starts it with what was written.

Rules it keeps:
- It starts only if the newest saved read-only check of this kit says VERDICT READY.
- It stops at the first step that does not end in DONE or NOTHING TO DO, and says what state that leaves.
- Each step is one pinned library; the runner (fx6_run.py) refuses any other bytes.
Nothing is written to a firmware file or to the camera's settings. What is written lives in the running camera's memory. A cold
boot (battery out for 10 seconds) removes it. On the A7S III the power switch removed it as well, so keep the FX6 switched on from
the first step to the last.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "CT1_usb_first_contact"))
sys.path.insert(0, str(HERE))
import ct1_common as c  # noqa: E402
import fx6_run  # noqa: E402

FIRMWARE = fx6_run.FIRMWARE
# The order is the one that ran on an FX6 (repo issue 2): memory first, the output size last. The earlier order (L5, L16, L19) put the
# output size in before its planes and its encoder, which is what stopped clips being written in issue 1. The put back is the mirror.
STEPS = {"apply": ("D16", "L5", "L19", "L16"), "putback": ("L17", "L20", "L6", "D17"), "screen": ("S16",), "screen-putback": ("S17",)}
E95 = ("On one FX6 (recording XAVC-I) the picture went BLACK after this step, with E95-311 on the screen, beeps and a blinking record lamp.",
       "The picture came back after the next step; the code stayed on the screen. Another FX6 (XAVC-L) showed nothing of the kind.",
       "If you see it: carry on with the next step. Do NOT pull the battery. Please note whether it happened and which Rec Format was set.")
RUNNER = HERE / "fx6_run.py"
LISTER = HERE.parent / "CT1_usb_first_contact" / "ct1_stage2_service.py"
SHOOT = ("the normal shooting screen (not playback, not a menu), Imager Scan Mode FF, Rec Format 3840x2160 (QFHD) at 23.98p "
         "in XAVC-I or XAVC-L 4:2:0 8-bit (NOT XAVC-L 4:2:2 10-bit), S&Q Motion off, Proxy Rec off")
USB = "connect the USB cable to this computer and, when the camera asks 'Connect USB Now?', choose Execute (Mass Storage)"


def say(text=""):
    print(text, flush=True)


def sessions():
    """Saved sessions of this kit, newest first: (folder, manifest)."""
    root = c.PRIVATE_ROOT
    out = []
    if root.is_dir():
        for folder in sorted((p for p in root.iterdir() if p.is_dir() and p.name.startswith("CT6_")), reverse=True):
            try:
                out.append((folder, json.loads((folder / "manifest.json").read_text(encoding="utf8"))))
            except (OSError, ValueError):
                continue
    return out


def last_check():
    """The newest saved read-only check of this kit that fetched a result: (folder name, ready?) or None. A check that stopped before the
    camera answered says nothing and is skipped. A check made with another kit (the FX3's fx3read, the A7S III's s3read) or with this kit's
    earlier helper does not count."""
    for folder, man in sessions():
        res = man.get("results", {})
        f = (res.get("ct6", {}).get("result") or {}).get("s3")
        if res.get("which") in ("check", "dump") and f:       # a dump makes every check the check makes, and gives the same verdict
            # this kit's helper version only: an earlier one (fx6read_v1) did not read the output-plane memory words
            current = fx6_run.LABELS[-1] + " " in f.get("header", "") and "ILME-FX6 6.02" in f.get("header", "")
            return folder.name, current and bool(f.get("ready")) and not f.get("identity_differs")
    return None


def last_result_sha():
    """The SHA-256 of the result the newest session fetched: the runner deletes a result left on the RAM disk only if it has this hash."""
    for _, man in sessions():
        try:
            return man["results"]["ct6"]["result"]["sha256"]
        except (KeyError, TypeError):
            continue
    return None


def usb_state():
    r = subprocess.run([sys.executable, "-I", "-B", str(LISTER), "--list"], capture_output=True, text=True, encoding="utf8", errors="replace", cwd=str(LISTER.parent))
    import re
    m = re.search(r"libusb sees: (\d+) Sony mass-storage device\(s\).*?, (\d+) Sony service device\(s\)", r.stdout)
    if not m:
        return "other"
    return "drive" if int(m.group(1)) == 1 and int(m.group(2)) == 0 else "service" if int(m.group(2)) else "other"


def wait_for_drive(first, timeout=600):
    asked, end = False, time.time() + timeout
    while usb_state() != "drive":
        if not asked:
            say()
            if first:
                say("The camera is not showing as a USB drive. Turn it on, set %s, then %s." % (SHOOT, USB))
            else:
                say(">>> Unplug the USB cable from the camera and plug it in again (choose Execute when it asks 'Connect USB Now?').")
                say(">>> Do NOT power the camera off or pull the battery: that would leave the steps half done.")
            say("Waiting for the camera (Ctrl+C to stop) ...")
            asked = True
        if time.time() > end:
            return False
        time.sleep(2)
    return True


def wait_for_replug(timeout=900):
    """Wait until the camera has been unplugged and shows up as a USB drive again. False on timeout."""
    end = time.time() + timeout
    while usb_state() != "other":                    # still plugged in, as a drive or in service mode
        if time.time() > end:
            return False
        time.sleep(1)
    while usb_state() != "drive":
        if time.time() > end:
            return False
        time.sleep(2)
    return True


def movie_session():
    """The closing read-only session (the debug dump): taken after the camera has restarted its picture with the patch."""
    say()
    say("=" * 78)
    say("One more session, and it only READS: the debug dump. It records what the camera ran after the apply (drive mode, sensor")
    say("registers, scaler) so the result can be checked.")
    say(">>> 1. Unplug the USB cable. The camera starts its picture again, now with the open-gate state.")
    say(">>> 2. Look at the LCD for five seconds (and point it at something with straight lines): what does it show?")
    say("       Write it down: the whole picture stretched sideways to fill the LCD (expected without the screen step) / the whole picture")
    say("       at 3:2 with black bars left and right (the screen step) / jitter, bands or anything else wrong / an error code (which one?).")
    say(">>> 3. Plug the USB cable in again and choose Execute when the camera asks 'Connect USB Now?'.")
    say(">>> Do NOT switch the camera off: on the A7S III the power switch removed the patch.")
    say("Waiting for the unplug and the replug (Ctrl+C to stop; the patch stays applied either way) ...")
    if not wait_for_replug():
        say("The camera did not come back as a USB drive. The steps are applied all the same.")
        say("Run dump_info later (camera on, not switched off since the apply) and send camera_private.")
        return
    cmd = [sys.executable, "-I", "-B", str(RUNNER), "dump", "--go", "--firmware-shown", FIRMWARE]
    clear = last_result_sha()
    if clear:
        cmd += ["--clear-result", clear]
    rc = subprocess.run(cmd).returncode
    which, f = step_outcome()
    say()
    if rc or which != "dump" or not f:
        say("The read-only session did not finish. The steps are applied all the same.")
        return
    decoded = f.get("decoded") or {}
    column = (decoded.get("sensor_registers") or {}).get("closest_column")
    mode = (decoded.get("core_log_record") or {}).get("drive_mode")
    if column != 1:                                  # the open-gate 4K 24p mode runs sensor register column 1 (as on the A7S III and FX3)
        say("NOTE: before this session the sensor was not in the open-gate mode (register column %s, not 1; drive mode %s)." % (column, mode))
        say("      Was the camera at FF, QFHD 23.98p (drive mode 0x8c0)? If not: set it, unplug, look at the LCD, replug, and run dump_info once more.")
    else:
        say("The sensor ran the open-gate full-height mode before this session (register column 1, drive mode %s)." % mode)
    say(">>> Unplug USB now. Then record a short test clip and check it on a computer (MediaInfo: 3840x2560).")


def step_outcome():
    for _, man in sessions():
        f = man.get("results", {}).get("ct6", {}).get("result", {}).get("s3")
        return (man.get("results", {}).get("which"), f) if f else (None, None)
    return None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=sorted(STEPS))
    ap.add_argument("--dry-run", action="store_true", help="show the steps and what each would send; nothing is sent")
    ap.add_argument("--screen", action="store_true", help="with apply: add the screen step S16 (it gave a broken preview on two FX6s; for testing)")
    ap.add_argument("--no-screen", action="store_true", help="with putback: leave out S17 (with apply it is the default and changes nothing)")
    ap.add_argument("--alt-memory", action="store_true", help="with apply: the memory step's variant R16 (dmm7slot_fx6_v2: no refused request in the allocator; not run on a camera) instead of D16")
    ap.add_argument("--no-movie-session", action="store_true", help="with apply or screen: leave out the closing read-only session (the debug dump)")
    ap.add_argument("--no-meta", action="store_true", help="with apply: the encoder step without the MXF header sites (N19): the files' MXF header keeps saying 3840x2160, 16:9")
    a = ap.parse_args()
    steps = STEPS[a.what]
    if a.no_screen and a.what not in ("apply", "putback"):
        raise SystemExit("--no-screen goes with apply or putback. Nothing was sent.")
    if (a.screen or a.alt_memory) and a.what != "apply":
        raise SystemExit("--screen and --alt-memory go with apply. Nothing was sent.")
    if a.screen and a.no_screen:
        raise SystemExit("--screen and --no-screen together. Nothing was sent.")
    if a.alt_memory:
        steps = tuple("R16" if k == "D16" else k for k in steps)
    if a.no_meta and a.what != "apply":
        raise SystemExit("--no-meta goes with apply (the put back L20 puts back either encoder step). Nothing was sent.")
    if a.no_meta:
        steps = tuple("N19" if k == "L19" else k for k in steps)
    # apply: the screen step only when asked for; putback: its put back unless left out (on a camera without it, it says NOTHING TO DO)
    with_screen = (a.screen if a.what == "apply" else not a.no_screen) and "S16" in fx6_run.WRITE_STEPS
    if a.what in ("apply", "putback") and with_screen:
        steps = steps + STEPS["screen"] if a.what == "apply" else STEPS["screen-putback"] + steps
    with_screen = with_screen or a.what in ("screen", "screen-putback")
    applying = a.what in ("apply", "screen")
    closing = applying
    for k in steps:                                  # every library must be the pinned one before anything starts
        if k not in fx6_run.WRITE_STEPS:
            raise SystemExit("Step %s is not in this kit. Nothing was sent." % k)
        name, sha, _ = fx6_run.WRITE_STEPS[k]
        p = fx6_run.S3 / name
        if not p.is_file() or c.sha256(p.read_bytes()) != sha:
            raise SystemExit("%s is missing or is not the pinned build. Nothing was sent." % name)
    say("FX6 6.02, %s: %d steps" % (a.what, len(steps)))
    for n, k in enumerate(steps, 1):
        say("  %d. %s  %s  (library %s...)" % (n, k, fx6_run.WRITE_STEPS[k][2], fx6_run.WRITE_STEPS[k][1][:16]))
    if closing and not a.no_movie_session:
        say("  then one read-only session (the debug dump) after the camera has restarted its picture. Nothing is written in it.")
    if a.dry_run:
        for k in steps:
            say()
            say("--- %s, what the session would send:" % k)
            r = subprocess.run([sys.executable, "-I", "-B", str(RUNNER), k, "--dry-run"], capture_output=True, text=True, encoding="utf8", errors="replace")
            say(r.stdout.rstrip() or r.stderr.rstrip())
        say()
        say("Dry run only: nothing was sent to any device.")
        return
    chk = last_check()
    if applying and (chk is None or not chk[1]):
        raise SystemExit("The newest saved read-only check of this kit %s. Run check_readonly first and get VERDICT READY. Nothing was sent."
                         % ("does not exist" if chk is None else "(%s) does not say READY" % chk[0]))
    say()
    say("This WRITES into the running camera's memory (not its firmware, not its settings).")
    if applying:
        say("Two FX6s have run this kit's steps (2026-11-25/26). With the memory step first, one of them records clean 3840x2560 XAVC-I 23.98p.")
        say("  NOT yet run on a camera: this exact order without the screen step, XAVC-L with the memory step, 25p%s."
            % (", and the memory variant R16" if a.alt_memory else ""))
        if a.screen:
            say("  The screen step gave a broken LCD preview on both FX6s (jitter; the picture in three sections). The recording was not affected.")
    else:
        say("It has to follow an apply of this kit.")
    say("A cold boot (battery out for 10 seconds) returns the camera to stock. On the A7S III the power switch did too:")
    say("so KEEP THE CAMERA SWITCHED ON from now until the script says it is finished.")
    say("Before you go on: a charged battery (or the AC adaptor), and %s." % SHOOT)
    if a.what == "apply":
        say("(If the open-gate state is already applied in this power-on, its steps will say NOTHING TO DO: that is fine.)")
    if input("Firmware version in the camera's menu: ").strip() != FIRMWARE:
        raise SystemExit("Not %s. Nothing was sent." % FIRMWARE)
    if input("Type YES to write to the camera's memory: ").strip() != "YES":
        raise SystemExit("Not confirmed. Nothing was sent.")
    for n, k in enumerate(steps, 1):
        if not wait_for_drive(n == 1):
            raise SystemExit("The camera did not show up as a USB drive. Stopped before step %d (%s)." % (n, k))
        say()
        say("=" * 78)
        say("Step %d of %d: %s, %s" % (n, len(steps), k, fx6_run.WRITE_STEPS[k][2]))
        cmd = [sys.executable, "-I", "-B", str(RUNNER), k, "--go", "--writes-memory", "--firmware-shown", FIRMWARE]
        clear = last_result_sha()
        if clear:
            cmd += ["--clear-result", clear]
        rc = subprocess.run(cmd).returncode
        which, f = step_outcome()
        if rc or which != k or not f or not f.get("ok"):
            say()
            say("STOPPED at step %d (%s): %s" % (n, k, "the session did not finish" if rc or which != k or not f else "outcome " + f["outcome"]))
            for ln in ((f or {}).get("problem_lines") or [])[:3]:
                say("  " + ln)
            if k in ("D16", "R16") and f and f.get("outcome") == "NOTHING WRITTEN":
                say("  The memory step found its table not as expected and wrote nothing. If the other memory variant is applied, run the put back first.")
            say("Steps before it are %s. To be sure of the camera's state: cold boot it (battery out for 10 seconds)." % ("applied" if applying else "put back"))
            say("Please send the newest folders in camera_private.")
            raise SystemExit(1)
        if k == "L5" and applying and n < len(steps):
            say()
            for ln in E95:
                say("NOTE  " + ln)
    say()
    say("All %d steps passed (%s)." % (len(steps), a.what))
    if a.what == "apply":
        say("XAVC-I QFHD and XAVC-L QFHD 4:2:0 8-bit at 23.98p now record a 3840x2560 picture.")
        say("  (Seen on an FX6 with XAVC-I at 23.98p. XAVC-L and 25p have not been shot with the memory step: please report.)")
        say("  If E95-311 is on the screen from the sensor step, it stays there with beeps and a blinking lamp until the camera is switched off;")
        say("  the tester's camera recorded all the same.")
        if a.no_meta:
            say("  The MXF header says 3840x2160, 16:9 (--no-meta): if an editor opens a clip squeezed, set it to 3840x2560 with square pixels.")
        else:
            say("  The MXF header (picture descriptor) now says 3840x2560 and 3:2, so editors should open the files at 3:2. Sony's XML (in the")
            say("  file and the M01.XML sidecar) still says 3840x2160, 16:9. Please report what MediaInfo says and how your editor opens them.")
        say("DO NOT RECORD XAVC-L 4:2:2 10-bit while it is applied: its encoder is still opened for 2160 rows (on the A7 IV that stopped a recording")
        say("  after about a second). XAVC-L 4:2:0 8-bit and XAVC-I are the formats this kit changes.")
        say("DO NOT PLAY CLIPS BACK ON THE CAMERA while it is applied: on two FX3s an open-gate clip showed 'unable to display' and a second try")
        say("  froze the camera until the battery was pulled. The FX6's playback with these clips has not been tried. Check the clips on a computer.")
    if with_screen and a.what in ("apply", "screen"):
        say("The screen step: the LCD was meant to show the whole picture at 3:2, with black bars left and right (the FX6's LCD is 16:9).")
        say("  On two FX6s it showed a broken preview instead (jitter; the picture in three sections). If yours does too: screen_putback removes it.")
        say("  Please report what the LCD, and an SDI or HDMI monitor if one is connected, show.")
    elif a.what == "apply":
        say("The LCD: without the screen step it shows the whole 3:2 picture stretched sideways to fill the 16:9 panel (a circle looks wide).")
        say("  The file is not stretched.")
    if closing:
        if a.no_movie_session:
            say(">>> Unplug USB now: the camera restarts its picture with the open-gate state.")
        else:
            movie_session()
        say()
        say("Use only FF, QFHD 3840x2160 at 23.98p, XAVC-I or XAVC-L 4:2:0 8-bit, while it is applied: other frame rates use drive modes this")
        say("  kit does not change (on the A7S III 60p distorted the picture and crashed the camera; 29.97p/50p/59.94p QFHD find no encoder")
        say("  entry and are refused), S35 and DCI 4K stay 16:9 (S35 QFHD would come out stretched), XAVC-L 4:2:2 10-bit is not changed.")
        say("  The memory step leaves 14 output planes instead of 17 and has only been run in QFHD: switch the camera off (battery out for")
        say("  10 seconds) before using HD, DCI 4K or S&Q.")
        say("If the camera stops or restarts: do NOT pull the battery yet. Replug USB and run dump_info, then send camera_private.")
        say("To return to stock: battery out for 10 seconds.")


if __name__ == "__main__":
    main()
