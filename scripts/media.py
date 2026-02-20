#!/usr/bin/env python3
"""media — CLI for the media resolver system.

Usage:
    python scripts/media.py verify

Exit codes:
    0  — all checks passed
    1  — verification failed
    2  — invalid usage
"""
import os
import subprocess
import sys
from pathlib import Path

_VERIFY_SCRIPT = Path(__file__).resolve().parent / "verify_media_integration.py"


def _run_verify(strict: bool = False) -> bool:
    cmd = [sys.executable, str(_VERIFY_SCRIPT)]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True).returncode == 0


def cmd_verify() -> int:
    run_dir_str = os.environ.get("RUN_DIR")
    if not run_dir_str:
        print("ERROR: media verification failed", file=sys.stderr)
        return 1
    run_dir = Path(run_dir_str)

    # Round 1
    if not _run_verify() or not _run_verify(strict=True):
        print("ERROR: media verification failed", file=sys.stderr)
        return 1
    bytes_1 = (run_dir / "AssetManifest.media.json").read_bytes()

    # Round 2
    if not _run_verify() or not _run_verify(strict=True):
        print("ERROR: media verification failed", file=sys.stderr)
        return 1
    bytes_2 = (run_dir / "AssetManifest.media.json").read_bytes()

    if bytes_1 != bytes_2:
        print("ERROR: media verification failed", file=sys.stderr)
        return 1

    print("OK: media verified")
    return 0


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] != "verify":
        print("Usage: python scripts/media.py verify", file=sys.stderr)
        sys.exit(2)
    sys.exit(cmd_verify())


if __name__ == "__main__":
    main()
