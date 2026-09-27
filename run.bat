@echo off
rem SAM Mask Studio launcher (uses the local .venv)
cd /d "%~dp0"
if exist ".tools\env.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command ". .\.tools\env.ps1; .\.venv\Scripts\python.exe -m src.main %*"
) else (
  ".venv\Scripts\python.exe" -m src.main %*
)
if errorlevel 1 pause
