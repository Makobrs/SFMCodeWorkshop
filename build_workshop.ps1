# Build the SFM Code Workshop MVP portable app.
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root
$PyInstaller = Join-Path $Root ".venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $PyInstaller)) { throw "missing .venv PyInstaller" }
$Target = Join-Path $Root "dist\SFMCodeWorkshop"
if (Test-Path $Target) { Remove-Item -LiteralPath $Target -Recurse -Force }
& $PyInstaller "sfm_workshop.spec" --noconfirm --clean --distpath (Join-Path $Root "dist") --workpath (Join-Path $Root "build_workshop_final")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
# PyInstaller on this Windows host can be denied copying Microsoft runtime
# DLLs (antivirus/ACL). The spec excludes them; restore them here.
$RuntimeNames = @(
    "vcruntime140.dll", "vcruntime140_1.dll",
    "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
    "msvcp140_codecvt_ids.dll", "concrt140.dll"
)
$RuntimeSource = Join-Path $Root ".venv\Lib\site-packages\PySide6"
$Internal = Join-Path $Target "_internal"
$Shiboken = Join-Path $Internal "shiboken6"
foreach ($Dir in @($Internal, $Shiboken)) {
    if (-not (Test-Path $Dir)) { continue }
    foreach ($Name in $RuntimeNames) {
        $From = Join-Path $RuntimeSource $Name
        if (Test-Path $From) { Copy-Item -LiteralPath $From -Destination (Join-Path $Dir $Name) -Force }
    }
}
Copy-Item -LiteralPath (Join-Path $Root "sfm_workshop\README.md") -Destination (Join-Path $Target "README.md") -Force
Copy-Item -LiteralPath (Join-Path $Root "sfm_workshop\NOTICE.md") -Destination (Join-Path $Target "NOTICE.md") -Force
$Zip = Join-Path $Root "dist\SFMCodeWorkshop-v0.2.0-win64.zip"
# Never ship user data or logs from a local verification run.
foreach ($Dir in @((Join-Path $Target "data"), (Join-Path $Target "logs"))) {
    if (Test-Path -LiteralPath $Dir) { Remove-Item -LiteralPath $Dir -Recurse -Force }
}
if (Test-Path $Zip) { Remove-Item -LiteralPath $Zip -Force }
Compress-Archive -LiteralPath $Target -DestinationPath $Zip -Force
$Hash = Get-FileHash -LiteralPath $Zip -Algorithm SHA256
Set-Content -LiteralPath (Join-Path $Root "dist\SHA256SUMS.txt") -Value ("{0}  {1}" -f $Hash.Hash.ToLower(), (Split-Path $Zip -Leaf)) -Encoding UTF8
Write-Host "built: $Target"
Write-Host "zip:   $Zip"
