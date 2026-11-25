"""Build `ogfile2560_xavc_fx6_v2` = `ogfile2560_xavc_fx6_v1` (the FX6 encoder step) + the MXF picture-descriptor sites of
build/mxf_meta_sites_fx6.py, so the files' MXF header says 3840 x 2560 and 3:2 (2026-11-26, the owner: "Yes, build it" = the FX3 kit's
metadata fix for the FX6's MXF files).

  C:/Python313/python.exe -B build/build_ogfile_fx6_meta.py

Checks: v1 rebuilds as it is (its sha256 is read from the file and kept in the output), every v2 site holds the stock bytes the module
expects, no v2 site overlaps v1's or a guard, and build/emu_mxf_meta_fx6.py (the FX6's own writer in Unicorn) passes. Sony's XML
(NonRealTimeMeta, inside the file and the sidecar) is not changed, as on the FX3 and the A7 IV.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import mxf_meta_sites_fx6 as S  # noqa: E402

DES = ROOT / "modding/designs"
V1, V2 = "ogfile2560_xavc_fx6_v1", "ogfile2560_xavc_fx6_v2"
LM = ROOT / "work/extracted/fx6_602/0700_part_image/dev/nflasha15/lib/libmpr.so"


def main():
    v1 = json.loads((DES / f"{V1}.json").read_text(encoding="utf8"))
    lm = LM.read_bytes()
    assert v1["artifact_sha256"]["libmpr.so"] == hashlib.sha256(lm).hexdigest()
    r = subprocess.run([sys.executable, "-B", str(ROOT / "build/emu_mxf_meta_fx6.py")], capture_output=True, text=True)
    assert r.returncode == 0 and "ALL PASS" in r.stdout, r.stdout[-2000:] + r.stderr[-2000:]
    new = S.sites(lm)
    guards = S.guards(lm)
    taken = [(int(p["file_off"], 16), len(p["old"]) // 2) for p in v1["patches"] if p["binary"] == "libmpr.so"]
    for a, old, nw, _ in new:
        assert lm[a:a + len(old)] == old and len(old) == len(nw) <= 16
        assert all(a + len(old) <= o or o + n <= a for o, n in taken), "a v2 site overlaps a v1 site"
        assert all(a + len(old) <= int(g["file_off"], 16) or int(g["file_off"], 16) + len(g["bytes"]) // 2 <= a for g in guards), "a guard overlaps a site"
    v2 = dict(v1)
    v2["design"] = V2
    v2["title"] = v1["title"] + "; the MXF picture descriptor says 3840x2560 and 3:2"
    v2["generated_by"] = "build/build_ogfile_fx6.py (v1) + build/build_ogfile_fx6_meta.py (the MXF header sites)"
    v2["patches"] = [dict(p) for p in v1["patches"]] + [
        {"binary": "libmpr.so", "kind": "L4-mxfmeta", "file_off": hex(a), "va": hex(a), "old": old.hex(), "new": nw.hex(), "note": why, "code": True}
        for a, old, nw, why in new]
    v2["libmpr_code_guards"] = [{"site": hex(a), "guards": guards if k == 0 else []} for k, (a, *_) in enumerate(new)]
    v2["summary"] = dict(v1["summary"])
    v2["summary"]["libmpr.so"] = {"sites": v1["summary"]["libmpr.so"]["sites"] + len(new), "bytes": v1["summary"]["libmpr.so"]["bytes"] + sum(len(o) for _, o, _, _ in new),
                                  "code_sites": len(new)}
    v2["mxf_meta"] = {
        "what": "muxMxfAvcFilePackageSectionPictureDescriptorCreate (libmpr 0x612dec, muxMxfAvcFinalize.c) writes the XAVC files' MXF picture descriptor. "
                "With v2, a QFHD clip's StoredHeight, SampledHeight and DisplayHeight are 2560 and its AspectRatio 3/2; the widths stay 3840",
        "sites": [{"file_off": hex(a), "stock": old.hex(), "new": nw.hex(), "note": why} for a, old, nw, why in new],
        "checked": "build/emu_mxf_meta_fx6.py -> evidence/fx6/mxf_meta_emu_fx6.json: the FX6's own writer, 30 cases (format codes 3/7/0xb/0x12/0x1d, "
                   "progressive and interlaced, both codec types): QFHD 3840x2160 16/9 -> 3840x2560 3/2; DCI 4096x2160, 2K, HD and 720 byte-identical; "
                   "the tag set has the same size",
        "not_changed": ["Sony's XML (NonRealTimeMeta, inside the file and the M01.XML sidecar): it keeps 3840 x 2160, 16:9, as on the FX3 and the A7 IV",
                        "the AVC sub-descriptor and the stream's level label",
                        "the HD muxer and the trimming tool's own descriptor writers (not on the XAVC recording path)"],
        "side_effects": ["XAVC-L QFHD 4:2:2 10-bit (excluded from the encoder step, not to be recorded while applied) would also be labelled 3840x2560 3:2",
                         "Sony's own fall-through from the 2048 case (codec type != 4) into the 3840 case: its aspect would read 3:2; the FX6 has no "
                         "2048-wide XAVC format, so no FX6 recording takes that path"]}
    v2["while_applied"] = [w for w in v1["while_applied"] if "MXF header" not in w] + [
        "the MXF picture descriptor says 3840x2560 and 3:2 (stored, sampled and display height 2560); Sony's XML still says 3840x2160, 16:9"]
    v2["base_design"] = {"name": V1, "sha256": hashlib.sha256((DES / f"{V1}.json").read_bytes()).hexdigest()}
    (DES / f"{V2}.json").write_text(json.dumps(v2, indent=1) + "\n", encoding="utf8", newline="\n")
    print(f"{V2}: {len(v2['patches'])} sites ({len(new)} new code sites in libmpr.so, {len(guards)} code guards); emulation passes")
    print("wrote", DES / f"{V2}.json")


if __name__ == "__main__":
    main()
