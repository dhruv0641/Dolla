#!/usr/bin/env python3
"""Return success only for a recently refreshed local worker heartbeat file."""

import os
from pathlib import Path
import time


path = Path(os.environ.get("FLOWX_WORKER_HEALTH_FILE", "/tmp/flowx-worker-ready"))
raise SystemExit(0 if path.is_file() and time.time() - path.stat().st_mtime < 10 else 1)
