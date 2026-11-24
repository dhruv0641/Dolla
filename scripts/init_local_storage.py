#!/usr/bin/env python3
"""Prepare the Docker-managed asset volume for the unprivileged runtime UID."""

import os
from pathlib import Path


ROOT = Path("/app/data")
ROOT.mkdir(parents=True, exist_ok=True)
ROOT.chmod(0o750)
os.chown(ROOT, 10001, 10001)
print("Managed storage volume initialized for UID 10001.")
