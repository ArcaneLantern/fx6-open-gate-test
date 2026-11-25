#!/bin/bash
# Build the FX6 write libraries from the A7 IV helper's source (helper/readcheck.c), with this build's tables and constants.
# usage: build_fx6_write.sh        (writes libJit_fx6_L<level>.so for levels 5 6 16 17 19 20, libJit_fx6_S16.so / _S17.so, and N19 / N20 when
#                                   kit.json names an encoder design without the header heights)
# The FX6 counterpart of helper_fx3/build_fx3_write.sh (the FX3 kit, which ran on two FX3s). Flags are those of helper/rebuild.sh.
# Differences from the FX3 build: the headers of gen_fx6_write.py, the FX6 6.02 libsencore.so to link against, and for levels 5/6 the
# sensor object's address (0x14a5aec, getter 0x85b640) and the drive-parameter pointer at control +0x664 (the FX3 has +0x698: the
# FX6's control object has 0x34 bytes less before it; constructor block 0x85d402, `str.w r0, [r4, #0x664]` at 0x85d536). Record 0x15c bytes.
set -e
H="$(cd "$(dirname "$0")" && pwd)"
SEN="$H/../../../work/extracted/fx6_602/0700_part_image/dev/nflasha15/lib/libsencore.so"
ENC="$(sed -n 's/.*"encoder": *"\([^"]*\)".*/\1/p' "$H/kit.json")"
ENC1="$(sed -n 's/.*"encoder_v1": *"\([^"]*\)".*/\1/p' "$H/kit.json")"
SCR="$(sed -n 's/.*"screen": *"\([^"]*\)".*/\1/p' "$H/kit.json")"
cd "$H/../helper"
CC=(../../../work/venv_zig/Scripts/python.exe -m ziglang cc -target aarch64-linux-gnu -std=gnu11 -O1 -Wall -Wextra -Werror -fPIC -shared -nostdlib -ffreestanding
    -fno-stack-protector -fno-builtin -fno-asynchronous-unwind-tables -Wl,-soname,libJit.so -Wl,--no-undefined -Wl,-z,now -g0 -s -Wl,-z,max-page-size=4096)
for L in 5 6; do
  "${CC[@]}" -DLEVEL=$L '-DSITES_H="expected_sites_ogsq_fx6_v1.h"' '-DDESIGN_LABEL="ogsq_fx6_v1"' -DIMAGER=0x14a5aecUL -DCTRL_DRVPARAM=0x664U \
    readcheck.c "$SEN" -o "$H/libJit_fx6_L$L.so"
done
for L in 16 17; do
  "${CC[@]}" -DLEVEL=$L '-DWORDS_H="expected_words_outsz2560_fx6_v1.h"' readcheck.c "$SEN" -o "$H/libJit_fx6_L$L.so"
done
# Levels 19/20: the encoder side (kit.json "encoder"); N19/N20: the same levels with the design without the file-header heights ("encoder_v1").
for L in 19 20; do
  "${CC[@]}" -DLEVEL=$L "-DMP_H=\"expected_mp_$ENC.h\"" -DAVCAM_PHYS=0x401000000UL readcheck.c -o "$H/libJit_fx6_L$L.so"
  if [ -n "$ENC1" ]; then
    "${CC[@]}" -DLEVEL=$L "-DMP_H=\"expected_mp_$ENC1.h\"" -DAVCAM_PHYS=0x401000000UL readcheck.c -o "$H/libJit_fx6_N$L.so"
  fi
done
# The LCD step: the same levels 16/17 with the screen words (kit.json "screen").
if [ -n "$SCR" ]; then
  for L in 16 17; do
    "${CC[@]}" -DLEVEL=$L "-DWORDS_H=\"expected_words_$SCR.h\"" readcheck.c "$SEN" -o "$H/libJit_fx6_S$L.so"
  done
fi
cd "$H"
for L in 5 6 16 17 19 20; do echo "$(sha256sum libJit_fx6_L$L.so | cut -d' ' -f1) $(stat -c %s libJit_fx6_L$L.so) level $L"; done
for N in N19 N20 S16 S17; do [ -f libJit_fx6_$N.so ] && echo "$(sha256sum libJit_fx6_$N.so | cut -d' ' -f1) $(stat -c %s libJit_fx6_$N.so) step $N"; done
true
