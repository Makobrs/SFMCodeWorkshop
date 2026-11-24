@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_workshop.ps1"
if errorlevel 1 pause
