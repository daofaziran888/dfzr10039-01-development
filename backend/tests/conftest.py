"""Test configuration: shared fixtures for all test modules."""
from __future__ import annotations

import pytest

# Ensure app package is importable
import sys
from pathlib import Path

# Add backend directory to sys.path if not already present
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))