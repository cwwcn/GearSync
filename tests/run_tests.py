"""Run the offline regression suite without third-party test dependencies."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_DIR / "scripts"
TESTS_DIR = PROJECT_DIR / "tests"

sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))
sys.argv[:] = [sys.argv[0]]

with patch(
    "socket.socket.connect",
    side_effect=AssertionError("offline tests must not open network connections"),
), patch(
    "socket.create_connection",
    side_effect=AssertionError("offline tests must not open network connections"),
):
    suite = unittest.defaultTestLoader.discover(
        start_dir=str(TESTS_DIR),
        pattern="test_*.py",
        top_level_dir=str(PROJECT_DIR),
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
