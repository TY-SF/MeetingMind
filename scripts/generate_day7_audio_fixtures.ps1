[CmdletBinding()]
param(
    [string]$FixturesDirectory = '',
    [string]$OutputDirectory = ''
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $FixturesDirectory) { $FixturesDirectory = Join-Path $root 'evaluation\audio_fixtures' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $root 'data\evaluation\day7-audio' }
$fixturesPath = [System.IO.Path]::GetFullPath($FixturesDirectory)
$outputPath = [System.IO.Path]::GetFullPath($OutputDirectory)
$dataRoot = [System.IO.Path]::GetFullPath((Join-Path $root 'data'))
if (-not $outputPath.StartsWith($dataRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "输出目录必须位于项目 data 目录内：$dataRoot"
}
if (-not (Test-Path -LiteralPath $fixturesPath -PathType Container)) {
    throw "未找到音频验收样本目录：$fixturesPath"
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { throw '未找到 ffmpeg' }
if (-not (Get-Command ffprobe -ErrorAction SilentlyContinue)) { throw '未找到 ffprobe' }

Add-Type -AssemblyName System.Speech
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
$tempPath = Join-Path $outputPath '.segments'
$tempFullPath = [System.IO.Path]::GetFullPath($tempPath)
if (-not $tempFullPath.StartsWith($outputPath, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "临时目录越过输出边界：$tempFullPath"
}
if (Test-Path -LiteralPath $tempFullPath) { Remove-Item -LiteralPath $tempFullPath -Recurse -Force }
New-Item -ItemType Directory -Force -Path $tempFullPath | Out-Null

function Get-VoiceMap {
    $synth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
    try {
        $voices = @($synth.GetInstalledVoices() | Where-Object Enabled | ForEach-Object VoiceInfo)
    } finally {
        $synth.Dispose()
    }
    $zh = @($voices | Where-Object { $_.Culture.Name -eq 'zh-CN' })
    if (-not $zh) { throw '未安装 zh-CN Windows TTS 语音，无法生成验收音频' }
    $male = @($zh | Where-Object Gender -eq 'Male')
    $female = @($zh | Where-Object Gender -eq 'Female')
    return @{
        zh_male = if ($male) { $male[0].Name } else { $zh[0].Name }
        zh_female = if ($female) { $female[0].Name } else { $zh[0].Name }
        zh_female_alt = if ($female.Count -gt 1) { $female[1].Name } elseif ($male) { $male[0].Name } else { $zh[0].Name }
    }
}

function Write-SpeechWave([string]$Text, [string]$VoiceName, [string]$Path) {
    $synth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
    try {
        $synth.SelectVoice($VoiceName)
        $synth.Rate = -1
        $synth.Volume = 100
        $synth.SetOutputToWaveFile($Path)
        $synth.Speak($Text)
        $synth.SetOutputToNull()
    } finally {
        $synth.Dispose()
    }
}

function Get-AudioDurationMs([string]$Path) {
    $raw = (& ffprobe -v error -show_entries format=duration -of 'default=noprint_wrappers=1:nokey=1' $Path 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw "ffprobe 读取失败：$Path" }
    $seconds = [double]::Parse($raw, [System.Globalization.CultureInfo]::InvariantCulture)
    return [int][Math]::Ceiling($seconds * 1000)
}

$voiceMap = Get-VoiceMap
$generated = [System.Collections.Generic.List[object]]::new()
try {
    foreach ($fixtureFile in Get-ChildItem -LiteralPath $fixturesPath -Filter '*.json' | Sort-Object Name) {
        $fixture = Get-Content -LiteralPath $fixtureFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $fixture.id -or -not $fixture.segments -or $fixture.segments.Count -lt 1) {
            throw "音频样本定义无效：$($fixtureFile.FullName)"
        }
        $caseTemp = Join-Path $tempFullPath $fixture.id
        New-Item -ItemType Directory -Force -Path $caseTemp | Out-Null
        $inputs = [System.Collections.Generic.List[string]]::new()
        $filters = [System.Collections.Generic.List[string]]::new()
        $offsetMs = 0
        $maxEndMs = 0
        $index = 0
        foreach ($segment in $fixture.segments) {
            $role = [string]$segment.voice_role
            $voiceName = $voiceMap[$role]
            if (-not $voiceName) { throw "未知 voice_role：$role" }
            $segmentPath = Join-Path $caseTemp ('segment-{0:D2}.wav' -f $index)
            Write-SpeechWave -Text ([string]$segment.text) -VoiceName $voiceName -Path $segmentPath
            $durationMs = Get-AudioDurationMs $segmentPath
            $overlapMs = if ($null -ne $segment.overlap_previous_ms) { [int]$segment.overlap_previous_ms } else { 0 }
            if ($index -gt 0) { $offsetMs = [Math]::Max(0, $offsetMs - $overlapMs) }
            $inputs.Add('-i'); $inputs.Add($segmentPath)
            $filters.Add("[$index`:a]aresample=16000,volume=0.82,adelay=$offsetMs`:all=1[a$index]")
            $endMs = $offsetMs + $durationMs
            $maxEndMs = [Math]::Max($maxEndMs, $endMs)
            $offsetMs = $endMs + 650
            $index++
        }

        $mixLabels = (0..($index - 1) | ForEach-Object { "[a$_]" }) -join ''
        $mixCount = $index
        $ffmpegArgs = [System.Collections.Generic.List[string]]::new()
        $ffmpegArgs.AddRange([string[]]@('-hide_banner', '-loglevel', 'error', '-y'))
        $ffmpegArgs.AddRange([string[]]$inputs)
        if ($fixture.audio_profile -eq 'noise_overlap') {
            $noiseSeconds = [Math]::Ceiling(($maxEndMs + 600) / 1000.0)
            $ffmpegArgs.AddRange([string[]]@('-f', 'lavfi', '-t', "$noiseSeconds", '-i', 'anoisesrc=color=pink:amplitude=0.006:sample_rate=16000'))
            $filters.Add("[$index`:a]volume=0.35[noise]")
            $mixLabels += '[noise]'
            $mixCount++
        }
        $filters.Add("${mixLabels}amix=inputs=${mixCount}:duration=longest:normalize=0,alimiter=limit=0.95[out]")
        $outputFile = Join-Path $outputPath ($fixture.id + '.wav')
        $ffmpegArgs.AddRange([string[]]@('-filter_complex', ($filters -join ';'), '-map', '[out]', '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', $outputFile))
        & ffmpeg @ffmpegArgs
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $outputFile)) {
            throw "ffmpeg 生成失败：$($fixture.id)"
        }
        $generated.Add([pscustomobject]@{
            id = [string]$fixture.id
            audio_file = [System.IO.Path]::GetFileName($outputFile)
            duration_ms = Get-AudioDurationMs $outputFile
            sha256 = (Get-FileHash -LiteralPath $outputFile -Algorithm SHA256).Hash.ToLowerInvariant()
            fixture_sha256 = (Get-FileHash -LiteralPath $fixtureFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            synthetic = $true
            contains_noise = ($fixture.audio_profile -eq 'noise_overlap')
            contains_overlap = [bool]($fixture.segments | Where-Object { $_.overlap_previous_ms -gt 0 })
        })
        Write-Host "[PASS] 已生成 $($fixture.id)" -ForegroundColor Green
    }
} finally {
    if (Test-Path -LiteralPath $tempFullPath) { Remove-Item -LiteralPath $tempFullPath -Recurse -Force }
}

$manifest = [pscustomobject]@{
    generated_at = (Get-Date).ToUniversalTime().ToString('o')
    source = 'Windows System.Speech synthetic fixtures'
    privacy = '仅包含项目自建合成会议文本，不含真实会议数据'
    cases = @($generated)
}
$manifestPath = Join-Path $outputPath 'manifest.json'
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
Write-Host "验收音频清单：$manifestPath" -ForegroundColor Cyan
