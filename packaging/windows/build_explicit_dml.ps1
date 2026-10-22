param(
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$Output,
    [string]$BuildDirectory = (Join-Path $env:TEMP 'openbroadcast-explicit-dml-build')
)
$ErrorActionPreference = 'Stop'
$Source = (Resolve-Path -LiteralPath $Source).Path
$Output = [System.IO.Path]::GetFullPath($Output)
$BuildDirectory = [System.IO.Path]::GetFullPath($BuildDirectory)
New-Item -ItemType Directory -Force -Path $BuildDirectory | Out-Null
$headers = @(
    @('onnxruntime_c_api.h', 'session', '9ed0d7054a4e74249467365b25b415d36f51a44a6349e2a994a1812e4723d1e2'),
    @('onnxruntime_ep_c_api.h', 'session', 'e94ac3490697bdb107844fa9d403952ee7136134132a057eae5c1207b57ce352'),
    @('dml_provider_factory.h', 'providers/dml', '893ddb645545bddad8c3f24bb768e97651c9ce45ec22076b435439889e4228c8')
)
foreach ($entry in $headers) {
    $target = Join-Path $BuildDirectory $entry[0]
    if (!(Test-Path -LiteralPath $target) -or (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $entry[2]) {
        $url = "https://raw.githubusercontent.com/microsoft/onnxruntime/v1.24.4/include/onnxruntime/core/$($entry[1])/$($entry[0])"
        Invoke-WebRequest -Uri $url -OutFile $target
    }
    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $entry[2]) {
        throw "Header checksum mismatch: $($entry[0])"
    }
}
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$installation = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (!$installation) { throw 'Install the Visual Studio C++ x64 tools and Windows SDK.' }
$vcvars = Join-Path $installation 'VC/Auxiliary/Build/vcvars64.bat'
# Import the compiler environment into this process; all intermediate files stay
# in BuildDirectory. The only requested deliverable is the Output DLL.
$environmentScript = Join-Path $BuildDirectory 'compiler_environment.cmd'
Set-Content -LiteralPath $environmentScript -Value @('@echo off', ('call "' + $vcvars + '" >nul'), 'if errorlevel 1 exit /b 1', 'set')
$environmentLines = & $env:ComSpec /d /c $environmentScript
if ($LASTEXITCODE -ne 0) { throw 'vcvars64.bat failed' }
foreach ($line in $environmentLines) {
    if ($line -match '^([^=]+)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
    }
}
$compiler = (Get-Command cl.exe -ErrorAction Stop).Source
$arguments = @('/nologo', '/std:c++17', '/EHsc', '/O2', '/LD', '/MT', "/I$BuildDirectory", $Source,
               "/Fo$(Join-Path $BuildDirectory 'explicit_dml.obj')", '/link', "/OUT:$Output",
               "/IMPLIB:$(Join-Path $BuildDirectory 'explicit_dml.lib')", 'd3d12.lib', 'dxgi.lib')
Push-Location -LiteralPath $BuildDirectory
try {
    & $compiler @arguments
    if ($LASTEXITCODE -ne 0) { throw "Compiler failed: $LASTEXITCODE" }
} finally {
    Pop-Location
}
Get-FileHash -LiteralPath $Output -Algorithm SHA256
