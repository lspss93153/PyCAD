# SPDX-License-Identifier: GPL-3.0-only
# Run from the extracted Windows install ZIP. Internet required for Python packages.
$ErrorActionPreference = 'Stop'
$root = if (Test-Path (Join-Path $PSScriptRoot 'pycad2d')) { $PSScriptRoot } else { (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path }
$target = Join-Path $env:LOCALAPPDATA 'Programs\PyCAD'
$venv = Join-Path $target '.venv'
function Locate-Python {
  $py = Get-Command py.exe -ErrorAction SilentlyContinue
  if ($py) {
    & $py.Source -3.12 -c 'import sys; assert sys.version_info[:2] == (3,12)' 2>$null
    if ($LASTEXITCODE -eq 0) { return [PSCustomObject]@{ Exe=$py.Source; Prefix='-3.12' } }
  }
  $candidate = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
  if (Test-Path $candidate) { return [PSCustomObject]@{ Exe=$candidate; Prefix='' } }
  $found = Get-Command python.exe -ErrorAction SilentlyContinue
  if ($found) {
    & $found.Source -c 'import sys; assert sys.version_info[:2] == (3,12)' 2>$null
    if ($LASTEXITCODE -eq 0) { return [PSCustomObject]@{ Exe=$found.Source; Prefix='' } }
  }
  return $null
}
try {
  $python = Locate-Python
  if (-not $python) {
    Write-Host 'Python 3.12 not found. Trying Windows Package Manager (winget)...'
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
      throw 'Python 3.12 and winget are unavailable. Install Python 3.12 from python.org, then rerun this installer.'
    }
    & winget.exe install --id Python.Python.3.12 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw 'winget could not install Python 3.12.' }
    $python = Locate-Python
    if (-not $python) { throw 'Python 3.12 installed but not detected yet. Restart Windows and run installer again.' }
  }
  Write-Host "Installing PyCAD v0.6.9.5 into $target"
  New-Item -ItemType Directory -Path $target -Force | Out-Null
  foreach ($item in @('main.py','pycad2d','requirements.txt','requirements_3d.txt','README.md','LICENSE','THIRD_PARTY_NOTICES.md','docs')) {
    $src = Join-Path $root $item
    if (Test-Path $src) {
      $dst = Join-Path $target $item
      if ((Test-Path $dst) -and (Test-Path $src -PathType Container)) { Remove-Item -Recurse -Force $dst }
      Copy-Item -Path $src -Destination $dst -Recurse -Force
    }
  }
  if (-not (Test-Path (Join-Path $venv 'Scripts\python.exe'))) {
    if ($python.Prefix) { & $python.Exe $python.Prefix -m venv $venv }
    else { & $python.Exe -m venv $venv }
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create Python virtual environment.' }
  }
  $exe = Join-Path $venv 'Scripts\python.exe'
  & $exe -m pip install -r (Join-Path $target 'requirements.txt')
  if ($LASTEXITCODE -ne 0) { throw 'Core Python dependencies failed to install.' }
  & $exe -m pip install -r (Join-Path $target 'requirements_3d.txt')
  if ($LASTEXITCODE -ne 0) { Write-Warning 'Optional 3D dependencies incomplete; STEP and some mesh tools may be unavailable.' }
  Push-Location $target
  try { & $exe -c 'import PySide6; import pycad2d' }
  finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { throw 'Python GUI verification failed.' }
  $wsh = New-Object -ComObject WScript.Shell
  $start = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\PyCAD.lnk'
  foreach ($link in @($start,(Join-Path ([Environment]::GetFolderPath('Desktop')) 'PyCAD.lnk'))) {
    $shortcut = $wsh.CreateShortcut($link)
    $shortcut.TargetPath = (Join-Path $venv 'Scripts\pythonw.exe')
    $shortcut.Arguments = '"' + (Join-Path $target 'main.py') + '"'
    $shortcut.WorkingDirectory = $target
    $shortcut.Description = 'PyCAD 2D/3D CAD v0.6.9.5'
    $shortcut.Save()
  }
  Write-Host 'Installation complete: Desktop + Start Menu shortcuts created.'
} catch {
  Write-Error $_.Exception.Message
  exit 1
}
