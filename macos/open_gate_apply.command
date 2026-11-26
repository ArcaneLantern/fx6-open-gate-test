#!/bin/bash
# FX6 (firmware 6.02): apply the open-gate state: QFHD 23.98p (FF) XAVC-I records 3840x2560 (four steps: output-plane memory, sensor, encoder, output size; then the read-only debug dump). The LCD shows the picture stretched sideways.
# WRITES into the camera's memory (not firmware, not settings). A cold boot (battery out for 10 seconds) returns it to stock; on the A7S III the power switch did too.
cd "$(dirname "$0")" || exit 1
exec "$PWD/run.sh" apply apply "$@"
