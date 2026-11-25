@echo off
rem FX6 (firmware 6.02): read-only debug dump for testers (logs, sensor and scaler state, LCD words, memory map).
rem READ-ONLY: nothing in the camera's memory or settings is changed. Extra options are passed on, e.g.  --dry-run  --selftest
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing: run setup.cmd first.
  pause
  exit /b 1
)
set /p FWV=Firmware version shown in the camera's menu (Maintenance, Version), e.g. 6.02:
".venv\Scripts\python.exe" -I -B "tools\camera_tests\CT6_memory_read_check\fx6_run.py" dump --go --firmware-shown %FWV% %*
echo.
echo The results are in windows\camera_private (newest folder). Zip that folder and send it back.
pause
