param(
    [string]$OutputDirectory = 'dist'
)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Create .venv and install requirements-build.txt first.'
}
Push-Location -LiteralPath $projectRoot
try {
    & $pythonPath -c "import onnxruntime as o; assert 'DmlExecutionProvider' in o.get_available_providers(), 'Install requirements-build.txt with DirectML first'"
    if ($LASTEXITCODE -ne 0) { throw 'DirectML runtime is missing.' }
    & $pythonPath -m PyInstaller --noconfirm --distpath $OutputDirectory OpenBroadcast.spec
    if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
    $appDirectory = Join-Path $OutputDirectory 'OpenBroadcast'
    $archivePath = Join-Path $OutputDirectory 'OpenBroadcast-windows-x64.zip'
    Copy-Item -LiteralPath (Join-Path $projectRoot 'README.md') -Destination (Join-Path $appDirectory 'README.md')
    Copy-Item -LiteralPath (Join-Path $projectRoot 'README.zh-CN.md') -Destination (Join-Path $appDirectory 'README.zh-CN.md')
    Compress-Archive -LiteralPath $appDirectory -DestinationPath $archivePath -Force
    Write-Output "Portable app: $appDirectory\OpenBroadcast.exe (keep the entire folder)."
    Write-Output "Archive: $archivePath"
} finally {
    Pop-Location
}
