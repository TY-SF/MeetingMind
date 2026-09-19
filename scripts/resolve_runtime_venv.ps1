[CmdletBinding()]
param(
    [switch]$RequireAudio
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

function Test-AudioRuntime([string]$PythonPath) {
    if (-not (Test-Path -LiteralPath $PythonPath)) { return $null }
    $probePath = Join-Path $PSScriptRoot 'check_audio_runtime.py'
    $result = & $PythonPath $probePath 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    $state = ($result | Out-String).Trim()
    if ($state -eq 'missing') { return $null }
    return $state
}

$candidates = @(
    (Join-Path $root 'backend\.venv'),
    (Join-Path $root '.venv')
)

if ($RequireAudio) {
    foreach ($candidate in $candidates) {
        $state = Test-AudioRuntime (Join-Path $candidate 'Scripts\python.exe')
        if ($state -eq 'audio-gpu') { Write-Output $candidate; exit 0 }
    }
    foreach ($candidate in $candidates) {
        if (Test-AudioRuntime (Join-Path $candidate 'Scripts\python.exe')) { Write-Output $candidate; exit 0 }
    }
    throw '未找到包含 WhisperX、pyannote 和 PyTorch 的可用音频运行环境。'
}

foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath (Join-Path $candidate 'Scripts\python.exe')) { Write-Output $candidate; exit 0 }
}
throw '未找到项目 Python 虚拟环境。'
