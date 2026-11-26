@echo off
rem FX6 (firmware 6.02): TEST: the open-gate state with the memory step's variant (no refused memory request in emulation; not run on a camera). Try it if open_gate_apply shows E95-311.
rem WRITES into the camera's memory (not firmware, not settings). A cold boot (battery out for 10 seconds) returns it to stock; on the A7S III the power switch did too.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing: run setup.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -I -B "tools\camera_tests\CT6_memory_read_check\fx6_apply.py" apply --alt-memory %*
echo.
pause
