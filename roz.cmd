@echo off
rem Multi-instance manager: roz list | status | check | start <name|all> | new <name> ... | build
rem See multi\roz.ps1 for the details.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0multi\roz.ps1" %*
