@echo off
rem Double-click shortcut for the kiminoto bot. The real logic is in roz.cmd
rem (instances.json holds the port and profile of every instance).
call "%~dp0roz.cmd" start kiminoto
