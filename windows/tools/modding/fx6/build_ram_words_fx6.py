"""Build `outsz2560_fx6_v1`: the FX6 6.02 counterpart of the FX3's working `outsz2560_fx3_v1` (one word of coprocessor RAM).

  C:/Python313/python.exe -B build/build_ram_words_fx6.py

The movie size table is filled at run time by 0x40793c (the FX3's 0x4008ec relinked: match_thumb exact, diff_consts 283 of 294
instructions aligned, only relocated branch targets and MOVW/MOVT pairs differ). build/emu_size_table.py runs it on the FX6 image:
base 0x1626b30, table at 0x1626b7c, 16 entries identical to the FX3's. The word changed is the second entry of size class 3:
3840 x 2160 -> 3840 x 2560; the two guards are the entry before it and the memory id after it, as on the FX3.
Design only; never run on a camera.
"""
import hashlib
import json
import struct
from pathlib import Path

import emu_size_table

ROOT = Path(__file__).resolve().parent.parent
BUILD, REF, NAME = "fx6_602", "fx3_702", "outsz2560_fx6_v1"


def main():
    t, rows, writes = emu_size_table.table(BUILD)
    r_t, r_rows, _ = emu_size_table.table(REF)
    assert t == 0x1626B7C and rows == r_rows, "the FX6 size table differs from the FX3's"
    site = t + 8 * 7
    assert rows[6] == (3840, 2160, 0x43E) and rows[7] == (3840, 2160, 0x2D9)
    ref = json.loads((ROOT / "modding/designs/outsz2560_fx3_v1.json").read_text(encoding="utf8"))
    img = (ROOT / "work/extracted" / BUILD / "0700_part_image/dev/nflasha8/cpapp-b.bin").read_bytes()
    sha = hashlib.sha256(img).hexdigest()
    out = {"design": NAME, "build": BUILD, "camera": "ILME-FX6 (FX6), firmware 6.02", "kind": "ram_words",
           "title": "Output size of the stock 4K movie request: 3840 x 2160 -> 3840 x 2560 (size class 3, second entry)",
           "status": "addresses from emulating the FX6's own size-table function; never read or written on an FX6. The same word change "
                     "(outsz2560_fx3_v1) works on two FX3s",
           "emulated_image_sha256": sha,                  # not `artifact_sha256`: the word is RAM the camera fills at run time, not a byte of the file
           "generated_by": "build/build_ram_words_fx6.py", "ported_from": "outsz2560_fx3_v1 (FX3 7.02, RAM 0x13c31c8)",
           "sites": [{"ram_address": hex(site), "old": struct.pack("<HH", 3840, 2160).hex(), "new": struct.pack("<HH", 3840, 2560).hex(),
                      "what": "size class 3, second entry: width, height"}],
           "guards": [{"ram_address": hex(site - 8), "bytes": struct.pack("<HHI", 3840, 2160, 0x43E).hex(), "what": "size class 3, first entry and the raw write buffer id"},
                      {"ram_address": hex(site + 4), "bytes": struct.pack("<I", 0x2D9).hex(), "what": "the output buffer's memory id"}],
           "precondition": "a movie picture set-up has run (the table is zero before; the FX6 has no stills mode, so it is filled once the camera has "
                           "started); the word is written during a USB session, while the camera's picture is stopped",
           "restore": ref["restore"],
           "emulated": {"function": "0x40793c", "table": hex(t), "entries_equal_fx3_702": True, "stores_into_block": len(writes)},
           "not_shown": ["anything on an FX6"] + ref["not_shown"][1:]}
    for s, g in ((out["sites"], ref["sites"]), (out["guards"], ref["guards"])):
        assert [(x.get("old"), x.get("new"), x.get("bytes")) for x in s] == [(x.get("old"), x.get("new"), x.get("bytes")) for x in g]
    dst = ROOT / "modding" / "designs" / f"{NAME}.json"
    dst.write_text(json.dumps(out, indent=1) + "\n", encoding="utf8", newline="\n")
    print(f"size table {t:#x} (FX3 {r_t:#x}): 16 entries equal; site {site:#x}")
    print("wrote", dst)


if __name__ == "__main__":
    main()
