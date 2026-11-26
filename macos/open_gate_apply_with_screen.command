#!/bin/bash
# FX6 (firmware 6.02): TEST: the open-gate state plus the LCD step (3:2 picture with side bars). On two FX6s the LCD step gave a broken preview.
# WRITES into the camera's memory (not firmware, not settings). A cold boot (battery out for 10 seconds) returns it to stock; on the A7S III the power switch did too.
cd "$(dirname "$0")" || exit 1
exec "$PWD/run.sh" apply apply --screen "$@"
