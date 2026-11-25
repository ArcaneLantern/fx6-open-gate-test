#!/bin/bash
# FX6 (firmware 6.02): apply the open-gate state: QFHD 23.98p (FF) records 3840x2560, and the LCD shows the 3:2 picture (four steps, then the read-only debug dump). NOT RUN ON ANY FX6 YET.
# WRITES into the camera's memory (not firmware, not settings). A cold boot (battery out for 10 seconds) returns it to stock; on the A7S III the power switch did too.
cd "$(dirname "$0")" || exit 1
exec "$PWD/run.sh" apply apply "$@"
