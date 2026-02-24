#!/usr/bin/env python3
"""media — CLI for the media resolver system.

Usage:
    media resolve --in <AssetManifest.json> --out <AssetManifest.media.json> [--strict]
    media verify

Subcommands:
    resolve   Resolve an AssetManifest to local files and write AssetManifest.media.json.
    verify    Run the resolver twice and assert byte-identical output (determinism check).
              Requires RUN_DIR env var pointing to a directory containing AssetManifest.json.

Exit codes:
    0  — success
    1  — resolver / validation error; or placeholder found in --strict mode
    2  — invalid usage or missing input file
"""
import os
import subprocess
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
_GENERATE_SCRIPT = _SCRIPTS_DIR / "generate_media.py"
_VERIFY_SCRIPT = _SCRIPTS_DIR / "verify_media_integration.py"

_USAGE = """\
Usage:
  media resolve --in <path> --out <path> [--strict]
  media verify
"""


# ---------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------

def cmd_resolve(argv: list[str]) -> int:
    """Delegate to generate_media.py, translating --in/--out to --input/--output."""
    import argparse

    parser = argparse.ArgumentParser(prog="media resolve", add_help=True)
    parser.add_argument("--in",  dest="input",  required=True, metavar="PATH",
                        help="Input AssetManifest.json")
    parser.add_argument("--out", dest="output", required=True, metavar="PATH",
                        help="Output AssetManifest.media.json")
    parser.add_argument("--strict", action="store_true",
                        help="Exit 1 if any asset is a placeholder")

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 2

    cmd = [
        sys.executable, str(_GENERATE_SCRIPT),
        "--input",  args.input,
        "--output", args.output,
    ]
    if args.strict:
        cmd.append("--strict")

    result = subprocess.run(cmd)
    return result.returncode


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print(_USAGE, file=sys.stderr)
        sys.exit(2)

    subcmd, rest = sys.argv[1], sys.argv[2:]

    if subcmd == "resolve":
        sys.exit(cmd_resolve(rest))
    elif subcmd == "verify":
        sys.exit(cmd_verify())
    else:
        print(f"Unknown subcommand: {subcmd!r}\n{_USAGE}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
