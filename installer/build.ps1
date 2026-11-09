param(
    [Parameter(Mandatory=$true)][string]$InnoCompiler,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $PSScriptRoot
$python = Join-Path $project ".venv\Scripts\python.exe"
$buildRoot = Join-Path $project ("build\release-" + [guid]::NewGuid().ToString("N"))
$distRoot = Join-Path $buildRoot "dist"
$payload = Join-Path $distRoot "VoiceTranslator"
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$output = (Resolve-Path -LiteralPath $OutputDirectory).Path
Push-Location $project
try {
    & $python -m PyInstaller --noconfirm --workpath (Join-Path $buildRoot "work") --distpath $distRoot VoiceTranslator.spec
    if ($LASTEXITCODE) { throw "PyInstaller failed: $LASTEXITCODE" }
    Move-Item -LiteralPath (Join-Path $payload "VoiceTranslator.exe") -Destination (Join-Path $payload "LiveTranslate.exe")
    $licenses = Join-Path $payload "licenses"
    New-Item -ItemType Directory -Path $licenses | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $project ".venv\Lib\site-packages") -Filter "*.dist-info" -Directory |
        ForEach-Object {
            $dist = $_
            $licenseDir = Join-Path $dist.FullName "licenses"
            if (Test-Path -LiteralPath $licenseDir) {
                Get-ChildItem -LiteralPath $licenseDir -Recurse -File | ForEach-Object {
                    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $licenses ($dist.Name + "-" + $_.Name))
                }
            }
        }
    & $InnoCompiler "/DPayloadDir=$payload" "/DOutputDir=$output" (Join-Path $PSScriptRoot "LiveTranslate.iss")
    if ($LASTEXITCODE) { throw "Inno Setup failed: $LASTEXITCODE" }
} finally {
    Pop-Location
}
