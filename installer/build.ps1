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
    & $python models.py
    if ($LASTEXITCODE) { throw "Model preparation failed: $LASTEXITCODE" }
    & $python -m PyInstaller --noconfirm --workpath (Join-Path $buildRoot "work") --distpath $distRoot VoiceTranslator.spec
    if ($LASTEXITCODE) { throw "PyInstaller failed: $LASTEXITCODE" }
    Move-Item -LiteralPath (Join-Path $payload "VoiceTranslator.exe") -Destination (Join-Path $payload "LiveTranslate.exe")
    $modelNames = @("whisper-small", "translate-en_ru-1_9", "translate-ru_en-1_9",
                    "translate-de_en-1_9", "vosk-model-small-en-us-0.15",
                    "vosk-model-small-ru-0.22", "vosk-model-spk-0.4")
    New-Item -ItemType Directory -Path (Join-Path $payload "data") | Out-Null
    foreach ($name in $modelNames) {
        Copy-Item -LiteralPath (Join-Path $project "data\$name") -Destination (Join-Path $payload "data") -Recurse
    }
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
