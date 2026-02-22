"""Pytest wrapper for third_party/contracts/tools/verify_contracts.py.

Ensures all contract goldens pass canonical-format, schema, and determinism
checks as part of the standard pytest run (setup.sh option 6).

Pattern: subprocess, matching test_verify_script.py.
"""

import subprocess
import sys
from pathlib import Path

VERIFIER = (
    Path(__file__).resolve().parents[2]
    / "third_party"
    / "contracts"
    / "tools"
    / "verify_contracts.py"
)


def test_contracts_all_goldens_pass() -> None:
    """All contract goldens pass canonical, schema, and determinism checks."""
    result = subprocess.run(
        [sys.executable, str(VERIFIER)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Contract verification failed:\n{result.stdout}\n{result.stderr}"
    )
