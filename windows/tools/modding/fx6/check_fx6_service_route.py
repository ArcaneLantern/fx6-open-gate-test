"""Compare the USB service route (Senser / Jiritsu) of the FX3 7.02 (proven) and the FX6 6.02.

Static, read-only. Writes evidence/fx6/service_route.json.
Records only offsets, sizes, hashes and yes/no facts; never the key bytes.

Run: C:\\Python313\\python.exe -B build\\check_fx6_service_route.py
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EX = os.path.join(HERE, "work", "extracted")
P15 = os.path.join("0700_part_image", "dev", "nflasha15")
REF, DST = "fx3_702", "fx6_602"
BUILDS = (REF, DST)
KEY_LEN = 512
MODULES = ("usbg_sen.ko", "usbg_storage.ko", "usb_extcmd.ko", "usb_f_mass_storage.ko", "usbg_uvc.ko")
NAMES = (b"start_authentication", b"onCompleteAuthentication", b"xxstep",
         b"/ramdsk/dev/mode", b"@JET_AUTHENTICATION", b"@IB_AUTH",
         b"JIRITSU_SET_FILE_PATH", b"JIRITSU_SET_FILE2", b"JIRITSU_GET_FILE2", b"JIRITSU_FILE_DELETE2")
JIT = (b"/tmp/jiritsu/libJit.so", b"/tmp/jiritsu/ramdsk_libJit/libJit.so",
       b"libJit.so copy error.", b"libJit.so crashed.", b"/tmp/jbusy", b"dlopen")


def rd(*parts):
    with open(os.path.join(EX, *parts), "rb") as f:
        return f.read()


def sha(b):
    return hashlib.sha256(b).hexdigest()


def key_offsets(sen):
    """The three 512-byte round constants: located in the FX3 file by the A7 IV offsets' content (F421)."""
    a7 = rd("a7iv_602", P15, "lib", "libsencore.so")
    return [a7[o:o + KEY_LEN] for o in (0x56330, 0x56530, 0x56730)]


def main():
    out = {"script": "build/check_fx6_service_route.py", "builds": list(BUILDS)}
    sen = {b: rd(b, P15, "lib", "libsencore.so") for b in BUILDS}
    out["libsencore"] = {b: {"size": len(d), "sha256": sha(d)} for b, d in sen.items()}
    keys = []
    for i, k in enumerate(key_offsets(sen)):
        keys.append({"round": i + 1, "key_sha256": sha(k),
                     **{b: (hex(sen[b].find(k)) if sen[b].find(k) >= 0 else None) for b in BUILDS}})
    out["auth_keys"] = keys
    out["auth_names"] = {n.decode(): {b: n in sen[b] for b in BUILDS} for n in NAMES}
    jit = {b: rd(b, P15, "lib", "libJiritsu.so") for b in BUILDS}
    out["libJiritsu"] = {b: {"size": len(d), "sha256": sha(d),
                             "jit_strings": {s.decode(): s in d for s in JIT}} for b, d in jit.items()}
    out["usb_modules"] = {}
    for m in MODULES:
        row = {}
        for b in BUILDS:
            p = os.path.join(EX, b, P15, "kmod", m)
            row[b] = sha(open(p, "rb").read())[:16] if os.path.exists(p) else None
        out["usb_modules"][m] = row
    out["kmod_lists"] = {b: sorted(x for x in os.listdir(os.path.join(EX, b, P15, "kmod")) if "usb" in x.lower())
                         for b in BUILDS if os.path.isdir(os.path.join(EX, b, P15, "kmod"))}
    di = {b: rd(b, P15, "share", "pmbp", "DeviceInfo.xml") for b in BUILDS}
    out["DeviceInfo_same"] = di[REF] == di[DST]
    dst = os.path.join(HERE, "evidence", "fx6", "service_route.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))
    ok = all(k[DST] for k in keys)
    print("keys present in FX6:", ok, "->", dst)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
