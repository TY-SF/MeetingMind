from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

root = Path("backend/data/fixtures/chinese_meeting_5min")
manifest = json.loads((root / "segments.json").read_text(encoding="utf-8-sig"))
configured_bin = os.getenv("MEETINGMIND_FFMPEG_BIN")
ffprobe = Path(configured_bin) / "ffprobe.exe" if configured_bin else None
if ffprobe is None or not ffprobe.is_file():
    resolved = shutil.which("ffprobe")
    if resolved:
        ffprobe = Path(resolved)
if ffprobe is None or not ffprobe.is_file():
    raise SystemExit("未找到 ffprobe；请将其加入 PATH，或设置 MEETINGMIND_FFMPEG_BIN。")
start_ms = 0
out = []
for item in manifest:
    duration = float(subprocess.check_output([
        str(ffprobe), "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", item["source_file"]
    ], text=True).strip())
    end_ms = start_ms + round(duration * 1000)
    out.append({
        "id": f"gold-{item['index'] + 1:03d}",
        "speaker": item["speaker"],
        "start_ms": start_ms,
        "end_ms": end_ms,
        "text": item["text"],
    })
    start_ms = end_ms
payload = {
    "audio_file": str(root / "chinese_meeting_5min.wav"),
    "language": "zh",
    "duration_ms": start_ms,
    "segments": out,
}
(root / "gold_transcript.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"duration_ms": start_ms, "segment_count": len(out), "output": str(root / "gold_transcript.json")}, ensure_ascii=False))
