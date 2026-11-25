#!/bin/bash
# FX6 (firmware 6.02): read-only check of the open-gate sites. Verdict READY / NOT READY.
# READ-ONLY: nothing in the camera's memory or settings is changed. Extra options are passed on, e.g.  --dry-run  --selftest
cd "$(dirname "$0")" || exit 1
read -r -p "Firmware version shown in the camera's menu (Setup, Version), e.g. 6.02: " FWV
echo "The results go to windows/camera_private (newest folder). Zip that folder and send it back."
exec "$PWD/run.sh" run check --go --firmware-shown "$FWV" "$@"
