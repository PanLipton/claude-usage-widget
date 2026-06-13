<#
.SYNOPSIS
    Set up a SECOND Claude Desktop account on Windows, side by side with your
    existing one.

.DESCRIPTION
    Claude Desktop ships as an MSIX/Store package whose login lives in a single,
    isolated per-package store -- so unlike Claude Code (CLI), it has no
    CLAUDE_CONFIG_DIR-style switch and the packaged app refuses to run twice.

    The supported isolation knob is Electron's --user-data-dir, but you can only
    pass it to a binary you launch directly, which the MSIX container blocks.
    So this script copies the Desktop payload out to a normal folder (a "loose"
    build) and launches THAT with its own --user-data-dir. The result is a fully
    separate Claude Desktop that you log into with your second account and run at
    the same time as your main one.

    Your primary account keeps using the normal Store app (launched by its AUMID);
    only the extra account uses this loose copy.

.PARAMETER DataDir
    Where the second account's Desktop profile (login, settings) is stored.
    Default: %USERPROFILE%\.claude-desktop-account2

.PARAMETER StandaloneDir
    Where the loose copy of the Desktop payload is placed.
    Default: %LOCALAPPDATA%\ClaudeDesktopStandalone

.PARAMETER NoLaunch
    Copy/refresh the files but don't open the app afterwards.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\setup_desktop_account.ps1
    # then, in the window that opens, sign in with your SECOND account
#>
[CmdletBinding()]
param(
    [string]$DataDir       = "$env:USERPROFILE\.claude-desktop-account2",
    [string]$StandaloneDir = "$env:LOCALAPPDATA\ClaudeDesktopStandalone",
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"

Write-Host "== Locating Claude Desktop package ==" -ForegroundColor Cyan
$pkg = Get-AppxPackage *laude* | Where-Object { $_.Name -eq "Claude" } | Select-Object -First 1
if (-not $pkg) { $pkg = Get-AppxPackage *laude* | Select-Object -First 1 }
if (-not $pkg) {
    throw "Claude Desktop (MSIX) not found. Install it first from https://support.claude.com/en/articles/10065433-install-claude-desktop"
}

$appId = ((Get-AppxPackageManifest $pkg).Package.Applications.Application | Select-Object -First 1).Id
$aumid = "$($pkg.PackageFamilyName)!$appId"
$src   = Join-Path $pkg.InstallLocation "app"
if (-not (Test-Path (Join-Path $src "Claude.exe"))) {
    throw "Could not find Claude.exe under $src"
}

Write-Host "  InstallLocation : $($pkg.InstallLocation)"
Write-Host "  AUMID (account 1): $aumid"

Write-Host "== Copying loose payload -> $StandaloneDir ==" -ForegroundColor Cyan
Write-Host "  (~500 MB; this runs again whenever Desktop updates, to refresh the copy)"
robocopy $src (Join-Path $StandaloneDir "app") /E /NFL /NDL /NJH /NJS /NP /MT:16 | Out-Null
$assets = Join-Path $pkg.InstallLocation "assets"
if (Test-Path $assets) {
    robocopy $assets (Join-Path $StandaloneDir "assets") /E /NFL /NDL /NJH /NJS /NP /MT:16 | Out-Null
}
$exe = Join-Path $StandaloneDir "app\Claude.exe"
if (-not (Test-Path $exe)) { throw "Copy failed: $exe missing" }

New-Item -ItemType Directory -Force $DataDir | Out-Null
Write-Host "  Loose exe : $exe"
Write-Host "  Data dir  : $DataDir"

Write-Host ""
Write-Host "== config.json snippet for the widget ==" -ForegroundColor Cyan
# Tokenize back to env-vars and double the backslashes for JSON, up front so the
# here-string below only does plain $var interpolation.
$bs = [char]92
$dataTok = $DataDir.Replace($env:USERPROFILE, '%USERPROFILE%').Replace("$bs", "$bs$bs")
$exeTok  = $exe.Replace($env:LOCALAPPDATA, '%LOCALAPPDATA%').Replace("$bs", "$bs$bs")
@"
  "launch_mode": "cli",
  "desktop": {
    "aumid": "$aumid",
    "standalone_exe": "$exeTok"
  },
  "accounts": [
    { "label": "claude1", "config_dir": "...", "desktop": "store" },
    { "label": "claude2", "config_dir": "...",
      "desktop": { "data_dir": "$dataTok" } }
  ]
"@ | Write-Host

if ($NoLaunch) {
    Write-Host "`nDone (skipped launch). Run the loose exe with --user-data-dir to sign in." -ForegroundColor Green
    return
}

Write-Host "`n== Launching the second Desktop -- sign in with your SECOND account ==" -ForegroundColor Green
Start-Process -FilePath $exe -ArgumentList "--user-data-dir=`"$DataDir`""
Write-Host "A fresh Claude Desktop window should open. Use it to log in; it runs"
Write-Host "alongside your main Desktop without logging the other one out."
