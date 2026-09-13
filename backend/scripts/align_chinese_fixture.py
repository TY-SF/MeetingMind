from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Register FFmpeg/PyTorch/torchcodec DLL directories before importing WhisperX.
from transcribe_smoke import configure_runtime
configure_runtime()
import torch
import whisperx

root = Path('backend/data/fixtures/chinese_meeting_5min')
transcript_path = root / 'transcript_whisperx.json'
transcript = json.loads(transcript_path.read_text(encoding='utf-8'))
segments = transcript['segments']
device = 'cuda' if torch.cuda.is_available() else 'cpu'
print(f'device={device}; loading zh alignment model')
model_a, metadata = whisperx.load_align_model(language_code='zh', device=device)
audio = whisperx.load_audio(str(root / 'chinese_meeting_5min.wav'))
aligned = whisperx.align(segments, model_a, metadata, audio, device, return_char_alignments=False)
output = {
    'audio_file': str(root / 'chinese_meeting_5min.wav'),
    'language': 'zh',
    'device': device,
    'segments': aligned.get('segments', []),
}
(root / 'transcript_aligned.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'output': str(root / 'transcript_aligned.json'), 'segment_count': len(output['segments']), 'word_timed_segments': sum(1 for s in output['segments'] if s.get('words'))}, ensure_ascii=False))
