@echo off
setlocal

rem Ragnarok.exe requires Administrator. Elevate this launcher first so
rem OpenKore and the game run at the same integrity level for DLL injection.
fltmc >NUL 2>&1
if errorlevel 1 (
  echo Requesting Administrator permission for XKore 1...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

set "OK_ROOT=C:\Users\silap\openkore"
set "RO_ROOT=D:\ROZCLUB"
set "PROFILE=%~dp0"
set "PERL=%PROFILE%runtime\perl-roz.exe"
set "INJECTOR=%PROFILE%runtime\roz-xkore-launcher.exe"

rem Isolated 32-bit Perl/OpenKore runtime for XKore 1 injection.
set "PERL5LIB=%PROFILE%runtime;%OK_ROOT%\src;%OK_ROOT%\src\deps;C:\Strawberry\perl\lib;C:\Strawberry\perl\site\lib;C:\Strawberry\perl\vendor\lib"
set "PATH=%PROFILE%runtime;C:\Strawberry\c\bin;C:\Users\silap\miniconda3;%SystemRoot%\System32;%PATH%"
set "LC_ALL=C"
set "LANG=C"

if not exist "%PERL%" (
  echo [ERROR] Prepared 32-bit Perl runtime is missing:
  echo         %PERL%
  pause
  exit /b 1
)

if not exist "%PROFILE%runtime\XSTools.dll" (
  echo [ERROR] Prepared XSTools.dll is missing:
  echo         %PROFILE%runtime\XSTools.dll
  pause
  exit /b 1
)

if not exist "%INJECTOR%" (
  echo [ERROR] Prepared suspended-process launcher is missing:
  echo         %INJECTOR%
  pause
  exit /b 1
)

if not exist "%OK_ROOT%\openkore.pl" (
  echo [ERROR] OpenKore not found at %OK_ROOT%
  pause
  exit /b 1
)

if not exist "%RO_ROOT%\Ragnarok.exe" (
  echo [ERROR] ROZCLUB client not found at %RO_ROOT%\Ragnarok.exe
  pause
  exit /b 1
)

rem Only one OpenKore per port. Other Ragnarok.exe windows (e.g. the kiminoto
rem bot, port 2352) may stay open.
netstat -ano -p tcp | findstr /C:"127.0.0.1:2351 " | findstr /I "LISTENING" >NUL
if not errorlevel 1 (
  echo [ERROR] Port 2351 is already in use - potato7's OpenKore is already running.
  echo         Close that OpenKore window ^(and its game window^) and run this file again.
  pause
  exit /b 1
)

if not exist "%PROFILE%logs" mkdir "%PROFILE%logs"

echo Starting OpenKore in XKore 1 auto mode...
start "OpenKore ROZCLUB XKore1" /D "%OK_ROOT%" cmd /k ""%PERL%" "%OK_ROOT%\openkore.pl" --control="%PROFILE%control;%OK_ROOT%\control" --tables="%PROFILE%tables;%OK_ROOT%\tables" --logs="%PROFILE%logs" --ai=on --interface=Console"

set /a WAIT_COUNT=0
:wait_for_xkore
netstat -ano -p tcp | findstr /C:"127.0.0.1:2351" | findstr /I "LISTENING" >NUL
if not errorlevel 1 goto xkore_ready
set /a WAIT_COUNT+=1
if %WAIT_COUNT% GEQ 60 goto xkore_timeout
ping -n 2 127.0.0.1 >NUL
goto wait_for_xkore

:xkore_timeout
echo [ERROR] XKore 1 did not open 127.0.0.1:2351 within 60 seconds.
echo         Check the OpenKore window for the actual error.
pause
exit /b 1

:xkore_ready
echo Starting ROZCLUB client, waiting for initialization, and loading NetRedirect...
for /f %%I in ('powershell.exe -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "RUN_TS=%%I"
set "INJECT_LOG=%PROFILE%logs\injector-%RUN_TS%.log"
"%INJECTOR%" "%RO_ROOT%\Ragnarok.exe" "%OK_ROOT%\NetRedirect-ROZ-IAT-v3.dll" >"%INJECT_LOG%" 2>&1
set "INJECT_EXIT=%ERRORLEVEL%"
type "%INJECT_LOG%"
if not "%INJECT_EXIT%"=="0" (
  echo [ERROR] ROZCLUB client injection failed. See the error above.
  echo         Log: %INJECT_LOG%
  pause
  exit /b 1
)

endlocal
