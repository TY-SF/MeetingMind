param(
  [string]$OutputRoot = "backend/data/fixtures/chinese_meeting_5min"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech

$ffmpeg = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\BtbN.FFmpeg.GPL.Shared.7.1_*\ffmpeg-*\bin\ffmpeg.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $ffmpeg) { $ffmpeg = Get-Command ffmpeg -ErrorAction Stop }
$ffmpegPath = $ffmpeg.FullName
$ffprobePath = Join-Path (Split-Path $ffmpegPath) 'ffprobe.exe'

$root = [IO.Path]::GetFullPath($OutputRoot)
$segmentsRoot = Join-Path $root 'segments'
New-Item -ItemType Directory -Force -Path $segmentsRoot | Out-Null

$utterances = @(
  @{ speaker='张敏'; voice='Microsoft Huihui Desktop'; text='大家下午好，今天是九月八日，我们召开产品迭代周会，主要确认二点零版本的范围、发布时间和验收安排。' },
  @{ speaker='李强'; voice='Microsoft Kangkang'; text='我先汇报一下当前进度。搜索功能的核心接口已经完成，前端页面也已经接通了基础数据，目前还剩错误提示和空状态需要补齐。' },
  @{ speaker='王芳'; voice='Microsoft Yaoyao'; text='设计这边已经完成了主要页面的视觉稿，不过移动端的上传区域还需要再调整一下，尤其是文件名过长时的显示。' },
  @{ speaker='张敏'; voice='Microsoft Huihui Desktop'; text='好的。关于二点零版本，我们先只保留搜索、会议详情和 Markdown 导出，批量上传和实时转录不放在这次发布范围里。' },
  @{ speaker='李强'; voice='Microsoft Kangkang'; text='我同意先收缩范围。批量上传虽然需求比较明确，但是会影响任务队列、错误处理和页面状态，短期内风险比较高。' },
  @{ speaker='王芳'; voice='Microsoft Yaoyao'; text='我有一个问题，会议详情里的转录文本是否需要支持全文编辑？用户可能会希望修正识别错误。' },
  @{ speaker='张敏'; voice='Microsoft Huihui Desktop'; text='第一版先不允许编辑完整转录，只允许修改摘要、结论和待办。原始转录要保留为证据，避免用户修改后无法追溯。' },
  @{ speaker='李强'; voice='Microsoft Kangkang'; text='那我会把转录区域做成只读，同时支持按时间戳查看。每个结论和待办都要显示对应的原文证据。' },
  @{ speaker='王芳'; voice='Microsoft Yaoyao'; text='这样比较清楚。我会在详情页增加一个提示，说明摘要和待办是人工审核前的 AI 草稿，用户保存前可以进行修改。' },
  @{ speaker='张敏'; voice='Microsoft Huihui Desktop'; text='接下来讨论音频处理。我们计划先用 FFmpeg 转成十六千赫兹单声道 WAV，再交给 WhisperX 处理。' },
  @{ speaker='李强'; voice='Microsoft Kangkang'; text='我已经在本机验证过这条链路，显卡是 RTX 四零六零，WhisperX 可以使用 CUDA 和 float 十六运行，短音频转录没有问题。' },
  @{ speaker='王芳'; voice='Microsoft Yaoyao'; text='中文会议录音的测试素材现在有了吗？如果只用英文合成音频，不能验证中文识别效果。' },
  @{ speaker='张敏'; voice='Microsoft Huihui Desktop'; text='还没有正式素材，所以我们先制作一份受控的中文会议录音。录音里安排三名说话人，并准备人工标注文本。' },
  @{ speaker='李强'; voice='Microsoft Kangkang'; text='我建议录音里加入几种容易出错的表达，比如下周五之前、月底、这个方案暂时不确定，以及有人打断发言的情况。' },
  @{ speaker='王芳'; voice='Microsoft Yaoyao'; text='我还可以加入一些产品名和英文技术术语，例如 API、Redis、WhisperX 和 Markdown，这样更接近真实会议。' },
  @{ speaker='张敏'; voice='Microsoft Huihui Desktop'; text='可以，但不要让台词过于规整。我们需要保留自然停顿、重复表达和少量口语化内容，才能观察模型在真实场景下的表现。' },
  @{ speaker='李强'; voice='Microsoft Kangkang'; text='关于时间安排，我负责在本周五，也就是九月十一日之前，补齐后端接口文档和处理失败时的错误码说明。' },
  @{ speaker='王芳'; voice='Microsoft Yaoyao'; text='我负责在明天下午之前完成上传页和会议详情页的最后一轮视觉调整，重点检查窄屏和长文件名场景。' },
  @{ speaker='张敏'; voice='Microsoft Huihui Desktop'; text='我的任务是下周一之前确认验收清单，并组织一次完整演示。演示时要展示成功、有警告和失败三种状态。' },
  @{ speaker='李强'; voice='Microsoft Kangkang'; text='这里我有一个风险提示。如果说话人分离失败，任务不应该直接失败，而是继续保存转录，并给用户一个明确的警告。' },
  @{ speaker='王芳'; voice='Microsoft Yaoyao'; text='同意。界面上可以显示部分说话人标签没有完成映射，但不能把不确定的内容伪装成确定结论。' },
  @{ speaker='张敏'; voice='Microsoft Huihui Desktop'; text='对于 AI 分析失败的情况，已经完成的音频预处理和转录结果也必须保留，用户可以稍后重试分析。' },
  @{ speaker='李强'; voice='Microsoft Kangkang'; text='任务状态我建议使用排队、预处理、转录、说话人分离、分析和完成这几个阶段，前端通过轮询展示当前阶段。' },
  @{ speaker='王芳'; voice='Microsoft Yaoyao'; text='轮询间隔先设置为两秒就可以。进度条不要显示过于精确的百分比，应该强调当前正在处理的阶段。' },
  @{ speaker='张敏'; voice='Microsoft Huihui Desktop'; text='关于模型输出，结论要区分已确认、提议、存在分歧和未解决。没有原文证据时，负责人和截止时间都要返回空值。' },
  @{ speaker='李强'; voice='Microsoft Kangkang'; text='日期解析以会议发生时间作为基准，不要只依赖服务器当前时间。像下周五这样的表达，需要同时保留原文和标准化日期。' },
  @{ speaker='王芳'; voice='Microsoft Yaoyao'; text='如果日期表达有歧义，比如月底但没有明确是哪一个月，页面应该保留原文，并提示用户人工确认。' },
  @{ speaker='张敏'; voice='Microsoft Huihui Desktop'; text='很好。现在确认一下发布目标：三天内完成可演示的 MVP，第四到第七天再补充姓名映射、ICS 导出和评估数据。' },
  @{ speaker='李强'; voice='Microsoft Kangkang'; text='我认为这个目标可以完成，前提是今天先把中文音频、转录、对齐和说话人分离的技术风险验证清楚。' },
  @{ speaker='王芳'; voice='Microsoft Yaoyao'; text='如果真实说话人分离模型暂时需要额外权限，我们可以先保留 Provider 接口，用固定的说话人标注结果完成前端演示。' },
  @{ speaker='张敏'; voice='Microsoft Huihui Desktop'; text='这是合理的降级方案，但 README 里必须如实说明哪些是真实处理，哪些是演示数据，不能把 Mock 功能写成已经完成。' },
  @{ speaker='李强'; voice='Microsoft Kangkang'; text='我会把今天的实验结果、模型版本、显卡配置和已知警告记录下来，方便后续在另一台电脑上复现。' },
  @{ speaker='王芳'; voice='Microsoft Yaoyao'; text='我会把三种任务状态的页面截图和操作步骤整理到文档里，并补充长文件名、空列表和失败重试的验收项。' },
  @{ speaker='张敏'; voice='Microsoft Huihui Desktop'; text='那今天的结论就确定了：先完成中文会议音频基准，再接入真实后端。大家按照刚才分配的任务推进，周五下午四点同步一次进展。' },
  @{ speaker='李强'; voice='Microsoft Kangkang'; text='收到，我会先处理音频链路和后端接口边界。' },
  @{ speaker='王芳'; voice='Microsoft Yaoyao'; text='收到，我会先处理页面细节和测试数据展示。' },
  @{ speaker='张敏'; voice='Microsoft Huihui Desktop'; text='好的，今天会议到这里。谢谢大家。'
  }
)

$manifest = @()
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.Rate = 2
$synth.Volume = 100

for ($i = 0; $i -lt $utterances.Count; $i++) {
  $item = $utterances[$i]
  $number = ($i + 1).ToString('000')
  $wav = Join-Path $segmentsRoot "segment_$number.wav"
  $synth.SelectVoice($item.voice)
  $synth.SetOutputToWaveFile($wav)
  $synth.Speak($item.text)
  $synth.SetOutputToNull()
  $manifest += [ordered]@{ index=$i; speaker=$item.speaker; voice=$item.voice; text=$item.text; source_file=$wav }
}
$synth.Dispose()

$concat = Join-Path $root 'concat.txt'
($manifest | ForEach-Object { "file '$($_.source_file.Replace("'", "'\''"))'" }) | Set-Content -Encoding UTF8 $concat
$raw = Join-Path $root 'chinese_meeting_5min_raw.wav'
$final = Join-Path $root 'chinese_meeting_5min.wav'
& $ffmpegPath -y -f concat -safe 0 -i $concat -c:a pcm_s16le $raw 2>$null | Out-Null
& $ffmpegPath -y -i $raw -ac 1 -ar 16000 -c:a pcm_s16le $final 2>$null | Out-Null
Remove-Item -LiteralPath $raw -Force

$manifestPath = Join-Path $root 'segments.json'
$manifest | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $manifestPath
$probe = & $ffprobePath -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 $final
[ordered]@{ file=$final; duration_seconds=[double]$probe; segment_count=$manifest.Count; speakers=($manifest.speaker | Select-Object -Unique) } | ConvertTo-Json | Write-Output

