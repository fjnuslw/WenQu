@echo off
rem get_offer launcher (double-click to run)
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\status.ps1" %*
pause
