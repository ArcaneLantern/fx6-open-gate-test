#!/bin/bash
# FX6 (firmware 6.02): put every step back to stock.
# WRITES into the camera's memory (not firmware, not settings). A cold boot (battery out for 10 seconds) returns it to stock; on the A7S III the power switch did too.
cd "$(dirname "$0")" || exit 1
exec "$PWD/run.sh" apply putback "$@"
