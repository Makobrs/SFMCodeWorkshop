@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m sfm_workshop
) else (
  python -m sfm_workshop
)
if errorlevel 1 pause
