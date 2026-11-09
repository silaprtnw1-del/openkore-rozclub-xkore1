@echo off
rem Multi-instance manager: roz list | status | check | start <name|all> | new <name> ... | remove <name> | build
rem See scripts\roz.ps1 for the details.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\roz.ps1" %*
