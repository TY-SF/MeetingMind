from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Move legacy <project>/meetings directories into <project>/data/meetings."
    )
    parser.add_argument("--source", type=Path, default=project_root / "meetings")
    parser.add_argument("--destination", type=Path, default=project_root / "data" / "meetings")
    parser.add_argument("--apply", action="store_true", help="Perform the move; otherwise only print the plan.")
    args = parser.parse_args()

    source = resolved(args.source)
    destination = resolved(args.destination)
    allowed_root = resolved(project_root)
    if not within(source, allowed_root) or not within(destination, allowed_root):
        raise SystemExit("source and destination must stay inside the MeetingMind project root")
    if source == destination:
        raise SystemExit("source and destination are the same directory")
    if not source.exists():
        print(json.dumps({"status": "nothing_to_migrate", "source": str(source)}, ensure_ascii=False))
        return 0
    if not source.is_dir():
        raise SystemExit(f"source is not a directory: {source}")

    unexpected_files = sorted(item.name for item in source.iterdir() if not item.is_dir())
    if unexpected_files:
        raise SystemExit(f"legacy meetings directory contains unexpected files: {unexpected_files}")

    moves: list[tuple[Path, Path]] = []
    for item in sorted(source.iterdir(), key=lambda value: value.name):
        target = destination / item.name
        if target.exists():
            raise SystemExit(f"destination collision: {target}")
        moves.append((item, target))

    summary = {
        "status": "ready" if moves else "nothing_to_migrate",
        "mode": "apply" if args.apply else "dry-run",
        "source": str(source),
        "destination": str(destination),
        "meeting_directory_count": len(moves),
        "meeting_ids": [item.name for item, _ in moves],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.apply or not moves:
        return 0

    destination.mkdir(parents=True, exist_ok=True)
    for item, target in moves:
        if not within(item, source) or not within(target, destination):
            raise SystemExit("refusing to move a path outside the verified roots")
        shutil.move(str(item), str(target))
        if item.exists() or not target.is_dir():
            raise SystemExit(f"move verification failed: {item} -> {target}")
    source.rmdir()
    print(json.dumps({"status": "migrated", "moved": len(moves)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
