"""Keep backend tests hermetic from the developer's local deployment configuration."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Test modules construct FastAPI apps during import and fixture setup. Point all of
# them at an intentionally missing env file before those imports happen so a local
# Bearer token, MySQL URL, or Compose override cannot change test expectations.
for name in (
    "MEETINGMIND_ENV_FILE",
    "MEETINGMIND_INFRA_ENV_FILE",
    "MEETINGMIND_DATABASE_URL",
    "MYSQL_HOST",
    "MYSQL_PORT",
    "MYSQL_DATABASE",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MEETINGMIND_API_TOKEN",
):
    os.environ.pop(name, None)

os.environ["MEETINGMIND_ENV_FILE"] = str(Path(tempfile.gettempdir()) / "meetingmind-pytest-isolated-missing.env")
