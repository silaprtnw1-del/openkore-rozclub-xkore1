@echo off
rem Double-click shortcut for the potato7 bot. The real logic is in roz.cmd
rem (instances.json holds the port and profile of every instance). The old
rem stand-alone launcher is in git history (commit eca0739); it did not load the
rem GUI plugin and still pointed at NetRedirect v3.
call "%~dp0roz.cmd" start potato7
