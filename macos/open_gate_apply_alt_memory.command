#!/bin/bash
# FX6 (firmware 6.02): TEST: the open-gate state with the memory step's variant (no refused memory request in emulation). It did not avoid E95-311 on the one FX6 that ran it.
# WRITES into the camera's memory (not firmware, not settings). A cold boot (battery out for 10 seconds) returns it to stock; on the A7S III the power switch did too.
cd "$(dirname "$0")" || exit 1
exec "$PWD/run.sh" apply apply --alt-memory "$@"
