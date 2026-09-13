from __future__ import annotations

import json
import os
from pathlib import Path

from transcribe_smoke import configure_runtime
configure_runtime()
import torch
import whisperx
from whisperx.diarize import DiarizationPipeline

root = Path('backend/data/fixtures/chinese_meeting_5min')
token = os.getenv('HF_TOKEN') or os.getenv('HUGGINGFACE_TOKEN')
if not token:
    raise SystemExit('HF_TOKEN is not configured; pyannote speaker diarization requires an accepted Hugging Face token.')

device = 'cuda' if torch.cuda.is_available() else 'cpu'
print(f'device={device}; starting speaker diarization')
audio = whisperx.load_audio(str(root / 'chinese_meeting_5min.wav'))
diarize_model = DiarizationPipeline(token=token, device=device)
diari = diarize_model(audio)
if hasattr(diari, 'to_dict'):
    records = diari.to_dict(orient='records')
else:
    records = diari

# pyannote stores the time range in a Segment object. Convert it to
# primitive JSON values before writing the result to disk.
output = []
for record in records:
    segment = record.get('segment') if isinstance(record, dict) else None
    start = record.get('start') if isinstance(record, dict) else None
    end = record.get('end') if isinstance(record, dict) else None
    if segment is not None:
        start = getattr(segment, 'start', start)
        end = getattr(segment, 'end', end)

    output.append({
        'start': float(start),
        'end': float(end),
        'speaker': str(record.get('speaker') or record.get('label', 'UNKNOWN')),
    })

(root / 'diarization.json').write_text(
    json.dumps(output, ensure_ascii=False, indent=2),
    encoding='utf-8',
)
print(f'wrote {root / "diarization.json"}')

