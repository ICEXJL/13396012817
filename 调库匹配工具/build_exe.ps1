$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$icuPaths = @(
    "${env:WINDIR}\System32\icu.dll"
    "${env:WINDIR}\System32\icuin.dll"
    "${env:WINDIR}\System32\icuuc.dll"
)
foreach ($icuPath in $icuPaths) {
    if (-not (Test-Path -LiteralPath $icuPath)) {
        throw "Required Windows ICU DLL not found: $icuPath"
    }
}

$pyinstallerArgs = @(
    '--noconfirm'
    '--clean'
    '--onefile'
    '--windowed'
    '--noupx'
    '--name'
    'diaoku_match'
    '--add-binary'
    "${env:WINDIR}\System32\icu.dll;."
    '--add-binary'
    "${env:WINDIR}\System32\icuin.dll;."
    '--add-binary'
    "${env:WINDIR}\System32\icuuc.dll;."
    'match_stock_gui.py'
)

& python -m PyInstaller @pyinstallerArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}
$builtExe = Join-Path $PSScriptRoot 'dist\diaoku_match.exe'
$displayExeName = [string]::Concat([char]0x8c03, [char]0x5e93, [char]0x5339, [char]0x914d, '.exe')
$displayExe = Join-Path $PSScriptRoot (Join-Path 'dist' $displayExeName)
if (-not (Test-Path -LiteralPath $builtExe)) {
    throw 'EXE output missing: dist\diaoku_match.exe'
}
Copy-Item -LiteralPath $builtExe -Destination $displayExe -Force
if (-not (Test-Path -LiteralPath $displayExe)) {
    throw "EXE output copy missing: $displayExe"
}
Remove-Item -LiteralPath $builtExe -Force
Write-Host "EXE build verified: $displayExe"
