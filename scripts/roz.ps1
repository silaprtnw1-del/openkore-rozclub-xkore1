# roz.ps1 - multi-instance manager for ROZCLUB + OpenKore (XKore 1)
#
# One game window + one OpenKore per instance. Everything is driven by
# ..\instances.json (the registry):
#   - ONE NetRedirect DLL serves every instance. It reads the OpenKore port from
#     the environment variable ROZ_XKORE_PORT of the game process (default 2351),
#     and this script sets that variable when it starts the game.
#   - every instance has its own profile folder (control\, tables\, logs\).
#
# Commands (run through roz.cmd):
#   list                          show the registry
#   status                        which instances are running right now
#   check                         validate the registry, profiles and DLL
#   start <name...|all>           start OpenKore and a bridged game client
#         [-NoGame] [-DryRun]       -NoGame: OpenKore only; -DryRun: print only
#   new <name> -Follow <leader>   create a support instance (next free port)
#       [-Role support] [-Port N]
#   new <name> -CloneFrom <inst>  create an instance by copying another one
#   build                         (re)build the DLL from the OpenKore sources
#
# Windows PowerShell 5.1 compatible. ASCII only on purpose.

[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$Command = 'help',
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Names,
    [string]$Role = 'support',
    [string]$Follow = '',
    [int]$Port = 0,
    [string]$CloneFrom = '',
    [switch]$NoGame,
    [switch]$DryRun,
    [switch]$DeleteFiles,
    [switch]$Elevated,
    # OpenKore console window: Normal | Minimized | Hidden (used by the GUI)
    [ValidateSet('Normal', 'Minimized', 'Hidden')][string]$ConsoleStyle = 'Normal',
    # GUI mode: no "Press Enter" pause, hidden elevated window, output to logs\gui-start.log
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2

$Script:Multi   = $PSScriptRoot                  # scripts\ (this file, templates\, bin\)
$Script:Root    = Split-Path -Parent $PSScriptRoot
$Script:BotsDir = 'bots'                         # one profile per bot: bots\<name>\control, tables, logs
$Script:RegPath = Join-Path $Script:Root 'instances.json'
$Script:PortEnv = 'ROZ_XKORE_PORT'
$Script:Utf8    = New-Object System.Text.UTF8Encoding($false)

function Write-Warn2([string]$m) { Write-Host "WARNING: $m" -ForegroundColor Yellow }
function Write-Err([string]$m)   { Write-Host "ERROR: $m" -ForegroundColor Red }

function Get-Prop($obj, [string]$name, $default = $null) {
    $p = $obj.PSObject.Properties[$name]
    if ($null -ne $p -and $null -ne $p.Value -and "$($p.Value)" -ne '') { return $p.Value }
    return $default
}

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------
function Get-Registry {
    if (-not (Test-Path -LiteralPath $Script:RegPath)) { throw "instances.json not found: $Script:RegPath" }
    return ([IO.File]::ReadAllText($Script:RegPath) | ConvertFrom-Json)
}

function Save-Registry($reg) {
    $json = $reg | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($Script:RegPath, $json, $Script:Utf8)
}

function Get-Instance($reg, [string]$name) {
    $m = @($reg.instances | Where-Object { $_.name -ieq $name })
    if ($m.Count -eq 0) {
        $known = (@($reg.instances | ForEach-Object { $_.name })) -join ', '
        throw "Unknown instance '$name'. Known instances: $known"
    }
    return $m[0]
}

function Get-ProfileDir($inst) {
    $rel = Get-Prop $inst 'profile' (Join-Path $Script:BotsDir $inst.name)
    return [IO.Path]::GetFullPath((Join-Path $Script:Root $rel))
}

function Get-Paths($reg) {
    $ok   = Get-Prop $reg 'openkoreRoot' 'C:\Users\silap\openkore'
    $game = Get-Prop $reg 'gameRoot' 'D:\ROZCLUB'
    return [pscustomobject]@{
        OpenKore   = $ok
        GameRoot   = $game
        GameExe    = Join-Path $game (Get-Prop $reg 'gameExe' 'Ragnarok.exe')
        Perl       = Join-Path $Script:Root 'runtime\perl-roz.exe'
        Injector   = Join-Path $Script:Root 'runtime\roz-xkore-launcher.exe'
        Dll        = Join-Path $Script:Root (Get-Prop $reg 'dll' 'scripts\bin\NetRedirect-ROZ-IAT-v4.dll')
        Strawberry = Get-Prop $reg 'strawberryRoot' 'C:\Strawberry'
        ExtraPath  = @(Get-Prop $reg 'extraPath' @())
    }
}

function Test-Registry($reg, $paths) {
    $problems = New-Object System.Collections.ArrayList
    $names = @{}
    $ports = @{}
    foreach ($i in @($reg.instances)) {
        $n = [string]$i.name
        $p = [int]$i.port
        if ($n -notmatch '^[A-Za-z0-9_-]+$') { [void]$problems.Add("[$n] name may only contain letters, digits, '_' and '-'") }
        if ($names.ContainsKey($n.ToLower())) { [void]$problems.Add("[$n] duplicate instance name") } else { $names[$n.ToLower()] = 1 }
        if ($p -lt 1024 -or $p -gt 65535) { [void]$problems.Add("[$n] port $p is outside 1024-65535") }
        if ($ports.ContainsKey($p)) { [void]$problems.Add("[$n] port $p is already used by instance $($ports[$p])") } else { $ports[$p] = $n }
        $cfg = Join-Path (Get-ProfileDir $i) 'control\config.txt'
        if (-not (Test-Path -LiteralPath $cfg)) { [void]$problems.Add("[$n] missing $cfg"); continue }
        $m = Select-String -LiteralPath $cfg -Pattern '^\s*XKore_port\s+(\d+)' | Select-Object -First 1
        if (-not $m) {
            [void]$problems.Add("[$n] config.txt has no XKore_port line (registry says $p)")
        } elseif ([int]$m.Matches[0].Groups[1].Value -ne $p) {
            [void]$problems.Add("[$n] config.txt has XKore_port $($m.Matches[0].Groups[1].Value) but instances.json says $p")
        }
    }
    return $problems.ToArray()
}

# --------------------------------------------------------------------------
# Process / port helpers
# --------------------------------------------------------------------------
function Get-ListenPid([int]$port) {
    $c = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { return [int]$c.OwningProcess }
    return 0
}

function Get-GamePid([int]$port) {
    # the game's end of the loopback connection: remote port = the OpenKore port
    $c = Get-NetTCPConnection -State Established -RemotePort $port -ErrorAction SilentlyContinue |
        Where-Object { $_.RemoteAddress -eq '127.0.0.1' } | Select-Object -First 1
    if ($c) { return [int]$c.OwningProcess }
    return 0
}

function Get-ProcName([int]$procId) {
    if ($procId -le 0) { return '-' }
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($p) { return $p.ProcessName }
    return '?'
}

# --------------------------------------------------------------------------
# list / status / check
# --------------------------------------------------------------------------
function Show-List($reg) {
    $rows = foreach ($i in @($reg.instances)) {
        $dir = Get-ProfileDir $i
        [pscustomobject]@{
            Name    = $i.name
            Port    = $i.port
            Role    = Get-Prop $i 'role' '-'
            Follow  = Get-Prop $i 'follow' '-'
            Profile = Get-Prop $i 'profile' (Join-Path $Script:BotsDir $i.name)
            Config  = $(if (Test-Path -LiteralPath (Join-Path $dir 'control\config.txt')) { 'ok' } else { 'MISSING' })
        }
    }
    Write-Host ($rows | Format-Table -AutoSize | Out-String)
}

function Show-Status($reg) {
    $rows = foreach ($i in @($reg.instances)) {
        $port = [int]$i.port
        $okPid = Get-ListenPid $port
        $gamePid = 0
        if ($okPid) { $gamePid = Get-GamePid $port }
        $state = 'stopped'
        if ($okPid -and $gamePid) { $state = 'running (game bridged)' }
        elseif ($okPid) { $state = 'OpenKore up, waiting for the game' }
        [pscustomobject]@{
            Name     = $i.name
            Port     = $port
            OpenKore = $(if ($okPid) { "$okPid ($(Get-ProcName $okPid))" } else { '-' })
            Game     = $(if ($gamePid) { "$gamePid ($(Get-ProcName $gamePid))" } else { '-' })
            State    = $state
        }
    }
    Write-Host ($rows | Format-Table -AutoSize | Out-String)
}

function Invoke-Check($reg, $paths) {
    $problems = @(Test-Registry $reg $paths)
    $warnings = New-Object System.Collections.ArrayList
    foreach ($f in @($paths.Perl, $paths.Injector, (Join-Path $paths.OpenKore 'openkore.pl'), $paths.GameExe)) {
        if (-not (Test-Path -LiteralPath $f)) { $problems += "missing file: $f" }
    }
    if (-not (Test-Path -LiteralPath $paths.Dll)) { $problems += "missing DLL: $($paths.Dll)  (run: roz build)" }
    foreach ($i in @($reg.instances)) {
        $srv = Join-Path (Get-ProfileDir $i) 'tables\servers.txt'
        if (-not (Test-Path -LiteralPath $srv)) { continue }
        $m = Select-String -LiteralPath $srv -Pattern '^\s*charBlockSize\s+(\d+)' | Select-Object -First 1
        if ($m -and [int]$m.Matches[0].Groups[1].Value -ne 175) {
            Write-Warn2 ("[{0}] tables\servers.txt has charBlockSize {1}; the ROZCLUB server uses 175. With another value only the character in slot 0 is read correctly (any other slot crashes OpenKore at map load). Change it to 175 before the next start." -f $i.name, $m.Matches[0].Groups[1].Value)
        }
    }
    foreach ($p in $problems) { Write-Err $p }
    if ($problems.Count -eq 0) { Write-Host "check: OK ($(@($reg.instances).Count) instances, DLL present)" -ForegroundColor Green }
    return $problems.Count
}

# --------------------------------------------------------------------------
# start
# --------------------------------------------------------------------------
function Initialize-OpenKoreEnv($paths) {
    $s = $paths.Strawberry
    $rt = Join-Path $Script:Root 'runtime'
    $env:PERL5LIB = (@($rt, (Join-Path $paths.OpenKore 'src'), (Join-Path $paths.OpenKore 'src\deps'),
                       "$s\perl\lib", "$s\perl\site\lib", "$s\perl\vendor\lib")) -join ';'
    $pathParts = @($rt, "$s\c\bin") + @($paths.ExtraPath) + @("$env:SystemRoot\System32")
    $env:PATH = ($pathParts -join ';') + ';' + $env:PATH
    $env:LC_ALL = 'C'
    $env:LANG = 'C'
}

function Start-Instance($paths, $inst, [bool]$noGame, [bool]$dry) {
    $name = [string]$inst.name
    $port = [int]$inst.port
    $dir = Get-ProfileDir $inst
    $control = Join-Path $dir 'control'
    $tables = Join-Path $dir 'tables'
    $logs = Join-Path $dir 'logs'

    $existing = Get-ListenPid $port
    if ($existing) {
        Write-Warn2 "[$name] port $port is already in use by pid $existing ($(Get-ProcName $existing)) - already running? skipped."
        return
    }
    if (-not (Test-Path -LiteralPath (Join-Path $control 'config.txt'))) { throw "[$name] $control\config.txt not found" }
    $needed = @($paths.Perl, (Join-Path $paths.OpenKore 'openkore.pl'))
    if (-not $noGame) { $needed += @($paths.Injector, $paths.GameExe, $paths.Dll) }
    foreach ($f in $needed) { if (-not (Test-Path -LiteralPath $f)) { throw "[$name] missing file: $f" } }
    New-Item -ItemType Directory -Force -Path $logs | Out-Null

    $okControl = Join-Path $paths.OpenKore 'control'
    $okTables = Join-Path $paths.OpenKore 'tables'
    # Plugins: OpenKore's own folder plus this profile's GUI bridge (plugins\gui_ipc).
    $okPlugins = Join-Path $paths.OpenKore 'plugins'
    $guiPlugin = Join-Path $Script:Root 'plugins\gui_ipc'
    $okArgs = '--control="{0};{1}" --tables="{2};{3}" --logs="{4}" --plugins="{5};{6}" --ai=on --interface=Console' -f $control, $okControl, $tables, $okTables, $logs, $okPlugins, $guiPlugin
    # cmd /k "title ... && "perl" "openkore.pl" args" : cmd strips the outer quotes.
    # A hidden window uses /c so no invisible cmd.exe is left behind after OpenKore exits.
    $keep = if ($ConsoleStyle -eq 'Hidden') { '/c' } else { '/k' }
    $cmdLine = '{5} "title ROZ {0} port {1} && "{2}" "{3}" {4}"' -f $name, $port, $paths.Perl, (Join-Path $paths.OpenKore 'openkore.pl'), $okArgs, $keep

    Write-Host "[$name] starting OpenKore on 127.0.0.1:$port ..."
    if ($dry) {
        Write-Host "  [dry-run] cmd.exe $cmdLine"
    } else {
        Start-Process -FilePath "$env:SystemRoot\System32\cmd.exe" -ArgumentList $cmdLine -WorkingDirectory $paths.OpenKore -WindowStyle $ConsoleStyle | Out-Null
        $deadline = (Get-Date).AddSeconds(60)
        while (-not (Get-ListenPid $port)) {
            if ((Get-Date) -gt $deadline) { throw "[$name] OpenKore did not open port $port within 60 seconds; check its window." }
            Start-Sleep -Milliseconds 500
        }
        Write-Host "[$name] OpenKore is listening (pid $(Get-ListenPid $port))."
    }

    if ($noGame) { Write-Host "[$name] -NoGame: game client not started."; return }

    $log = Join-Path $logs ('injector-{0}.log' -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
    $injArgs = '"{0}" "{1}"' -f $paths.GameExe, $paths.Dll
    Write-Host "[$name] starting a game client bridged to port $port ..."
    if ($dry) {
        Write-Host "  [dry-run] set $($Script:PortEnv)=$port ; `"$($paths.Injector)`" $injArgs"
        return
    }
    [Environment]::SetEnvironmentVariable($Script:PortEnv, [string]$port, 'Process')
    try {
        $p = Start-Process -FilePath $paths.Injector -ArgumentList $injArgs -PassThru -NoNewWindow `
            -RedirectStandardOutput $log -RedirectStandardError ($log + '.err')
        $null = $p.Handle
        $p.WaitForExit()
        $code = $p.ExitCode
    } finally {
        [Environment]::SetEnvironmentVariable($Script:PortEnv, $null, 'Process')
    }
    if ($code -ne 0) { throw "[$name] injector failed (exit code $code). See $log" }

    $deadline = (Get-Date).AddSeconds(25)
    $gamePid = 0
    while (-not $gamePid -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
        $gamePid = Get-GamePid $port
    }
    if ($gamePid) {
        Write-Host "[$name] bridged: game pid $gamePid <-> OpenKore port $port. Log in with this character in the new game window." -ForegroundColor Green
    } else {
        Write-Warn2 "[$name] game started but no bridge to port $port was seen within 25 seconds (see $log)."
    }
}

function Invoke-Start($reg, $paths, [string[]]$wanted) {
    $wanted = @($wanted | Where-Object { $_ })
    if ($wanted.Count -eq 0) { throw 'usage: roz start <name...|all> [-NoGame] [-DryRun]' }
    $targets = @()
    if ($wanted -contains 'all') { $targets = @($reg.instances) }
    else { foreach ($n in $wanted) { $targets += Get-Instance $reg $n } }

    $problems = @(Test-Registry $reg $paths)
    if ($problems.Count -gt 0) { foreach ($p in $problems) { Write-Err $p }; throw 'registry check failed; fix the problems above first (roz check).' }

    $launchesGame = (-not $NoGame) -and (-not $DryRun)
    if ($launchesGame -and -not (Test-Admin)) {
        Write-Host 'The game client needs Administrator rights; opening an elevated window (UAC prompt)...'
        $argText = '-NoProfile -ExecutionPolicy Bypass -File "{0}" start {1} -Elevated -ConsoleStyle {2}' -f $PSCommandPath, (($wanted | ForEach-Object { '"' + $_ + '"' }) -join ' '), $ConsoleStyle
        if ($Quiet) {
            $argText += ' -Quiet'
            Start-Process -FilePath 'powershell.exe' -ArgumentList $argText -Verb RunAs -WindowStyle Hidden | Out-Null
        } else {
            Start-Process -FilePath 'powershell.exe' -ArgumentList $argText -Verb RunAs | Out-Null
        }
        return
    }

    Initialize-OpenKoreEnv $paths
    $delay = [int](Get-Prop $reg 'startDelaySeconds' 6)
    for ($k = 0; $k -lt $targets.Count; $k++) {
        Start-Instance $paths $targets[$k] ([bool]$NoGame) ([bool]$DryRun)
        if ($k -lt $targets.Count - 1 -and -not $DryRun) { Start-Sleep -Seconds $delay }
    }
    Write-Host ''
    Show-Status (Get-Registry)
}

# --------------------------------------------------------------------------
# new
# --------------------------------------------------------------------------
function ConvertTo-Crlf([string]$t) { return ($t -replace "`r?`n", "`r`n") }

function Expand-Template([string]$path, [hashtable]$vars) {
    $t = [IO.File]::ReadAllText($path)
    foreach ($k in $vars.Keys) { $t = $t.Replace('{{' + $k + '}}', [string]$vars[$k]) }
    $m = [regex]::Match($t, '\{\{[A-Z_]+\}\}')
    if ($m.Success) { throw "unreplaced placeholder $($m.Value) in $path" }
    return $t
}

function New-Instance($reg, $paths, [string]$name, [string]$role, [string]$follow, [int]$port, [string]$cloneFrom) {
    if (-not $name) { throw 'usage: roz new <name> -Follow <leader>   |   roz new <name> -CloneFrom <instance>' }
    if ($name -notmatch '^[A-Za-z0-9_-]+$') { throw "bad name '$name' (letters, digits, '_' and '-' only)" }
    if (@($reg.instances | Where-Object { $_.name -ieq $name }).Count -gt 0) { throw "instance '$name' already exists" }

    if ($port -eq 0) {
        $used = @($reg.instances | ForEach-Object { [int]$_.port })
        $port = ($used | Measure-Object -Maximum).Maximum + 1
        while ($used -contains $port -or (Get-ListenPid $port)) { $port++ }
    } elseif (@($reg.instances | Where-Object { [int]$_.port -eq $port }).Count -gt 0) {
        throw "port $port is already used by another instance"
    }
    if ($port -lt 1024 -or $port -gt 65535) { throw "port $port is outside 1024-65535" }

    $rel = Join-Path $Script:BotsDir $name
    $dir = [IO.Path]::GetFullPath((Join-Path $Script:Root $rel))
    if ((Test-Path -LiteralPath $dir) -and (@(Get-ChildItem -LiteralPath $dir -Force).Count -gt 0)) { throw "folder already exists and is not empty: $dir" }

    $baseDir = [IO.Path]::GetFullPath((Join-Path $Script:Root (Get-Prop $reg 'baseProfile' '.')))
    $dllName = [IO.Path]::GetFileName($paths.Dll)
    $today = Get-Date -Format 'yyyy-MM-dd'
    $cfgText = $null

    if ($cloneFrom) {
        $src = Get-Instance $reg $cloneFrom
        $srcControl = Join-Path (Get-ProfileDir $src) 'control'
        $cfgText = [IO.File]::ReadAllText((Join-Path $srcControl 'config.txt'))
        if ($cfgText -notmatch '(?m)^XKore_port\s+\d+') { throw "source config has no XKore_port line" }
        $cfgText = [regex]::Replace($cfgText, '(?m)^XKore_port\s+\d+', "XKore_port $port")
        $cfgText = [regex]::Replace($cfgText, '(?m)^XKore_dll\s+.*$', "XKore_dll $dllName")
        $cfgText = "# $name - cloned from $($src.name) on $today by roz.ps1 (XKore_port/XKore_dll rewritten)`n" + $cfgText
        $role = Get-Prop $src 'role' 'farmer'
    } elseif ($role -eq 'support') {
        if (-not $follow) { throw "role 'support' needs -Follow <leader name> (the character to follow and buff)" }
        $vars = @{ NAME = $name; PORT = $port; DLL_NAME = $dllName; ROLE = $role; DATE = $today; FOLLOW = $follow; HEAL_TARGETS = "$follow, $name" }
        $cfgText = (Expand-Template (Join-Path $Script:Multi 'templates\base.txt') $vars) + "`n" +
                   (Expand-Template (Join-Path $Script:Multi 'templates\role-support.txt') $vars)
    } else {
        throw "unknown role '$role' (available: support; or use -CloneFrom <instance>)"
    }

    New-Item -ItemType Directory -Force -Path (Join-Path $dir 'control'), (Join-Path $dir 'tables'), (Join-Path $dir 'logs') | Out-Null
    [IO.File]::WriteAllText((Join-Path $dir 'control\config.txt'), (ConvertTo-Crlf $cfgText), $Script:Utf8)

    if ($cloneFrom) {
        foreach ($f in @(Get-ChildItem -LiteralPath $srcControl -File -Filter '*.txt')) {
            if ($f.Name -in @('config.txt', 'sys.txt')) { continue }
            Copy-Item -LiteralPath $f.FullName -Destination (Join-Path $dir 'control') -Force
        }
    } else {
        Copy-Item -LiteralPath (Join-Path $baseDir 'control\timeouts.txt') -Destination (Join-Path $dir 'control\timeouts.txt') -Force
    }
    # sys.txt: same plugins as the base profile, minus the market scanner (it reads
    # the token of the first game client it finds, so it belongs to one instance only)
    $sysLines = [IO.File]::ReadAllText((Join-Path $baseDir 'control\sys.txt')) -split "`r?`n"
    $sysOut = foreach ($l in $sysLines) {
        if ($l -match '^loadPlugins_list\s+(.*)$') {
            $keep = @($Matches[1].Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ -and $_ -notin @('rozclub_market', 'crashtrace') })
            'loadPlugins_list ' + ($keep -join ',')
        } else { $l }
    }
    [IO.File]::WriteAllText((Join-Path $dir 'control\sys.txt'), (ConvertTo-Crlf ($sysOut -join "`n")), $Script:Utf8)
    # servers.txt comes from the template, NOT from the base profile: the server's
    # character block is 175 bytes (see FINDINGS-0065-A07D.md). With 155 only slot 0
    # parses, and a character in any other slot crashes OpenKore in map_loaded
    # ("Attempt to STORE non blessed reference").
    Copy-Item -LiteralPath (Join-Path $Script:Multi 'templates\servers.txt') -Destination (Join-Path $dir 'tables\servers.txt') -Force

    $entry = [ordered]@{ name = $name; port = $port; profile = $rel; role = $role }
    if ($follow) { $entry['follow'] = $follow }
    $entry['created'] = $today
    $reg.instances = @($reg.instances) + [pscustomobject]$entry
    Save-Registry $reg

    Write-Host "Created instance '$name' (role $role, port $port) in $dir" -ForegroundColor Green
    Write-Host "  next: edit $dir\control\config.txt if needed, then:  roz start $name"
}

function Remove-Instance($reg, [string]$name, [bool]$deleteFiles) {
    if (-not $name) { throw 'usage: roz remove <name> [-DeleteFiles]' }
    $inst = Get-Instance $reg $name
    $port = [int]$inst.port
    $running = Get-ListenPid $port
    if ($running) { throw "[$($inst.name)] is running (port $port, pid $running). Close its OpenKore and game windows first." }
    $dir = Get-ProfileDir $inst
    $reg.instances = @($reg.instances | Where-Object { $_.name -ine $name })
    Save-Registry $reg
    Write-Host "Removed '$($inst.name)' from instances.json."
    if ($deleteFiles) {
        $instancesRoot = [IO.Path]::GetFullPath((Join-Path $Script:Root $Script:BotsDir)) + '\'
        if (-not $dir.StartsWith($instancesRoot, [StringComparison]::OrdinalIgnoreCase)) {
            Write-Warn2 "profile folder $dir is not under $instancesRoot - not deleting it."
        } elseif (Test-Path -LiteralPath $dir) {
            Remove-Item -LiteralPath $dir -Recurse -Force
            Write-Host "Deleted $dir"
        }
    } else {
        Write-Host "Profile folder kept: $dir  (use -DeleteFiles to delete it too)"
    }
}

# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------
function Build-Dll($paths) {
    $srcDir = Join-Path $paths.OpenKore 'src\auto\XSTools\win32'
    $gpp = Join-Path $paths.Strawberry 'c\bin\g++.exe'
    if (-not (Test-Path -LiteralPath $gpp)) { throw "g++ not found: $gpp" }
    $files = @('netredirect.cpp', 'utils-netredirect.cpp', 'common.h', 'utils.h')
    foreach ($f in $files) { if (-not (Test-Path -LiteralPath (Join-Path $srcDir $f))) { throw "source missing: $srcDir\$f" } }

    $work = Join-Path $env:TEMP 'roz-netredirect-build'
    if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force }
    New-Item -ItemType Directory -Path $work | Out-Null
    foreach ($f in $files) { Copy-Item -LiteralPath (Join-Path $srcDir $f) -Destination $work }

    # Patch: the XKore port comes from the game process environment (ROZ_XKORE_PORT),
    # falling back to XKORE_SERVER_PORT (2351) from common.h when it is not set.
    $cppPath = Join-Path $work 'netredirect.cpp'
    $cpp = [IO.File]::ReadAllText($cppPath)
    $marker = '#include <string.h>'
    $call = 'createSocket (XKORE_SERVER_PORT)'
    if ([regex]::Matches($cpp, [regex]::Escape($marker)).Count -ne 1) { throw "patch anchor '$marker' not found exactly once in netredirect.cpp (source changed?)" }
    if ([regex]::Matches($cpp, [regex]::Escape($call)).Count -ne 1)   { throw "patch anchor '$call' not found exactly once in netredirect.cpp (source changed?)" }
    $helper = @'

#include <stdlib.h>

/* ROZ multi-instance: the launcher sets ROZ_XKORE_PORT in the game's environment,
   so one DLL can serve any number of OpenKore instances. */
static int getKoreServerPort ()
{
	char buf[16];
	DWORD n = GetEnvironmentVariableA ("ROZ_XKORE_PORT", buf, sizeof (buf));
	if (n > 0 && n < sizeof (buf)) {
		int p = atoi (buf);
		if (p >= 1024 && p <= 65535)
			return p;
	}
	return XKORE_SERVER_PORT;
}
'@
    $cpp = $cpp.Replace($marker, $marker + $helper).Replace($call, 'createSocket (getKoreServerPort ())')
    [IO.File]::WriteAllText($cppPath, $cpp, $Script:Utf8)

    $outTmp = Join-Path $work 'NetRedirect.dll'
    $env:PATH = (Join-Path $paths.Strawberry 'c\bin') + ';' + $env:PATH
    # same flags that reproduce the deployed v3 DLL byte-for-byte (checked 2026-11-06)
    $gArgs = @('-shared', '-O2', '-fpermissive', '-w', '-Wl,--image-base=0x67200000', '-o', $outTmp,
               'netredirect.cpp', 'utils-netredirect.cpp', '-lws2_32', '-static')
    $log = Join-Path $work 'gpp.log'
    $p = Start-Process -FilePath $gpp -ArgumentList $gArgs -WorkingDirectory $work -PassThru -NoNewWindow -Wait `
        -RedirectStandardOutput $log -RedirectStandardError ($log + '.err')
    $null = $p.Handle
    if ($p.ExitCode -ne 0) { throw ("g++ failed (exit $($p.ExitCode)): " + ((Get-Content -LiteralPath ($log + '.err') -ErrorAction SilentlyContinue) -join ' ')) }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $paths.Dll) | Out-Null
    try {
        Copy-Item -LiteralPath $outTmp -Destination $paths.Dll -Force
    } catch {
        throw "built OK but cannot overwrite $($paths.Dll) - a running game still has it loaded. Close the game windows and run 'roz build' again. ($($_.Exception.Message))"
    }
    $info = @("built $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') by roz.ps1 build", "port: env $($Script:PortEnv), default 2351",
              (& $gpp --version | Select-Object -First 1))
    foreach ($f in $files) { $info += ('{0}  {1}  (source)' -f (Get-FileHash -LiteralPath (Join-Path $srcDir $f) -Algorithm SHA256).Hash.Substring(0, 16), $f) }
    [IO.File]::WriteAllText((Join-Path (Split-Path -Parent $paths.Dll) 'BUILD-INFO.txt'), ($info -join "`r`n") + "`r`n", $Script:Utf8)
    Write-Host "Built $($paths.Dll) ($((Get-Item -LiteralPath $paths.Dll).Length) bytes)" -ForegroundColor Green
}

function Show-Help {
    Write-Host @'
roz - ROZCLUB multi-instance manager (one OpenKore + one game window per instance)

  roz list                           instances in instances.json
  roz status                         what is running (OpenKore pid, game pid, bridge)
  roz check                          validate registry, ports, profiles, DLL
  roz start <name...|all>            start OpenKore + a bridged game client (asks for Administrator)
      -NoGame                          only OpenKore
      -DryRun                          print what would be run
  roz new <name> -Follow <leader>    new support instance (next free port, config from templates)
  roz new <name> -CloneFrom <inst>   new instance copied from another one (e.g. a second farmer)
      -Port N                          choose the port yourself
  roz remove <name> [-DeleteFiles]   take an instance out of instances.json (and its folder, if asked)
  roz build                          rebuild scripts\bin\NetRedirect-ROZ-IAT-v4.dll from the OpenKore sources
'@
}

# --------------------------------------------------------------------------
$Script:Pause = $Elevated -and -not $Quiet
if ($Quiet) {
    $guiLogDir = Join-Path $Script:Root 'logs'
    New-Item -ItemType Directory -Force -Path $guiLogDir | Out-Null
    try { Start-Transcript -Path (Join-Path $guiLogDir 'gui-start.log') -Force | Out-Null } catch { }
}
try {
    switch ($Command.ToLower()) {
        'help'   { Show-Help }
        'list'   { Show-List (Get-Registry) }
        'status' { Show-Status (Get-Registry) }
        'check'  { $r = Get-Registry; if ((Invoke-Check $r (Get-Paths $r)) -gt 0) { exit 1 } }
        'start'  { $r = Get-Registry; Invoke-Start $r (Get-Paths $r) $Names }
        'new'    { $r = Get-Registry; New-Instance $r (Get-Paths $r) ($Names | Select-Object -First 1) $Role $Follow $Port $CloneFrom }
        'remove' { $r = Get-Registry; Remove-Instance $r ($Names | Select-Object -First 1) ([bool]$DeleteFiles) }
        'build'  { $r = Get-Registry; Build-Dll (Get-Paths $r) }
        default  { Write-Err "unknown command '$Command'"; Show-Help; exit 2 }
    }
} catch {
    Write-Err $_.Exception.Message
    if ($Quiet) { try { Stop-Transcript | Out-Null } catch { } }
    if ($Script:Pause) { Read-Host 'Press Enter to close' | Out-Null }
    exit 1
}
if ($Quiet) { try { Stop-Transcript | Out-Null } catch { } }
if ($Script:Pause) { Read-Host 'Press Enter to close' | Out-Null }
