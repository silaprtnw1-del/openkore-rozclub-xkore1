@echo off
rem ROZ Bot Control - desktop GUI for every bot in instances.json.
set "PYW=C:\Users\silap\miniconda3\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw.exe"
start "" "%PYW%" "%~dp0gui\roz_gui.pyw"
