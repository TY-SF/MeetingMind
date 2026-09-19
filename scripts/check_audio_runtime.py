from __future__ import annotations

import importlib.util


def main() -> int:
    required = all(importlib.util.find_spec(name) is not None for name in ("whisperx", "pyannote"))
    if not required:
        print("missing")
        return 2
    try:
        import torch
    except ImportError:
        print("missing")
        return 2
    print("audio-gpu" if torch.cuda.is_available() else "audio-cpu")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
