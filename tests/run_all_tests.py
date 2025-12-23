"""
Test runner script to execute all tests.

Usage:
    python tests/run_all_tests.py
    python tests/run_all_tests.py -v  # verbose
    python tests/run_all_tests.py tests/test_satellites.py  # run specific test file
"""

import sys
from pathlib import Path

import pytest

if __name__ == "__main__":
    # Add project root to path
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))

    # Run pytest with provided arguments or default to all tests
    args = sys.argv[1:] if len(sys.argv) > 1 else ["tests/", "-v"]
    exit_code = pytest.main(args)
    sys.exit(exit_code)

