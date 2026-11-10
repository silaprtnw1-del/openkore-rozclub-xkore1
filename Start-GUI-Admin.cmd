@echo off
rem ROZ Bot Control as Administrator.
rem Needed for auto-login: Windows UIPI blocks SendInput from a normal process
rem to the elevated game window. One UAC prompt here replaces the per-bot one.
setlocal
set "PYW=C:\Users\silap\miniconda3\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw.exe"
set "SCRIPT=%~dp0gui\roz_gui.pyw"
powershell.exe -NoProfile -Command "$q=[char]34; Start-Process -FilePath $env:PYW -ArgumentList ($q + $env:SCRIPT + $q) -Verb RunAs"
