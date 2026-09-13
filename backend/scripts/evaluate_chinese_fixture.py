from __future__ import annotations

import json
from pathlib import Path

root = Path('backend/data/fixtures/chinese_meeting_5min')
gold = json.loads((root / 'gold_transcript.json').read_text(encoding='utf-8'))
pred = json.loads((root / 'transcript_whisperx_timed.json').read_text(encoding='utf-8'))

def normalize(text: str) -> str:
    return ''.join(ch for ch in text if not ch.isspace() and ch not in '，。！？、,.!?')

def distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]

gold_text = normalize(''.join(x['text'] for x in gold['segments']))
pred_text = normalize(''.join(x['text'] for x in pred['segments']))
errors = distance(gold_text, pred_text)
summary = {
    'audio_duration_seconds': round(gold['duration_ms'] / 1000, 3),
    'gold_segment_count': len(gold['segments']),
    'predicted_segment_count': len(pred['segments']),
    'gold_characters': len(gold_text),
    'predicted_characters': len(pred_text),
    'character_edit_distance': errors,
    'character_error_rate_estimate': round(errors / max(len(gold_text), 1), 4),
    'note': 'This fixture uses Windows TTS voices, so the estimate is a pipeline smoke signal rather than a human-speech accuracy benchmark.'
}
(root / 'evaluation.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False))
