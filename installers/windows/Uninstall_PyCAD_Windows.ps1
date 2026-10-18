# SPDX-License-Identifier: GPL-3.0-only
$ErrorActionPreference = 'Stop'
$target = Join-Path $env:LOCALAPPDATA 'Programs\PyCAD'
$start = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\PyCAD.lnk'
$desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'PyCAD.lnk'
foreach ($link in @($start, $desktop)) { if (Test-Path $link) { Remove-Item $link -Force } }
if (Test-Path $target) { Remove-Item $target -Recurse -Force }
Write-Host 'PyCAD removed. Your drawings and the application settings were left untouched.'
