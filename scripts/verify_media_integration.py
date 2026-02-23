#!/usr/bin/env python3
"""Permanent integration verification for the media resolver.

Usage:
    RUN_DIR=/path/to/run python scripts/verify_media_integration.py

Exit codes:
    0  — all checks passed
    1  — validation error or determinism failure
    2  — RUN_DIR missing or AssetManifest.json not found
"""

import argparse
import json
import os
import sys
from pathlib import Path

import jsonschema

# Ensure project root is on sys.path so resolvers/* and models/* are importable
# when the script is invoked from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from resolvers.local import LocalAssetResolver  # noqa: E402

# ---------------------------------------------------------------------------
# Contract schemas — loaded once at import time relative to project root.
# ---------------------------------------------------------------------------
_CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "third_party" / "contracts" / "schemas"
_SCHEMA_IN  = json.loads((_CONTRACTS_DIR / "AssetManifest.v1.json").read_text(encoding="utf-8"))
_SCHEMA_OUT = json.loads((_CONTRACTS_DIR / "AssetManifest.media.v1.json").read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true",
                        help="Fail if any resolved asset is a placeholder.")
    args = parser.parse_args()
    strict = args.strict

    # 1. Resolve RUN_DIR
    run_dir_str = os.environ.get("RUN_DIR")
    if not run_dir_str:
        print("ERROR: RUN_DIR environment variable is not set.", file=sys.stderr)
        sys.exit(2)

    run_dir = Path(run_dir_str)
    manifest_path = run_dir / "AssetManifest.json"

    if not manifest_path.exists():
        print(f"ERROR: {manifest_path} not found.", file=sys.stderr)
        sys.exit(2)

    # 2. Load orchestrator AssetManifest.json
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: Failed to load AssetManifest.json: {exc}", file=sys.stderr)
        sys.exit(1)

    # 2b. Validate input manifest against contract
    try:
        jsonschema.validate(instance=manifest, schema=_SCHEMA_IN)
    except jsonschema.ValidationError as exc:
        print(
            f"ERROR: input manifest does not conform to AssetManifest.v1.json: {exc.message}",
            file=sys.stderr,
        )
        sys.exit(1)

    # 3. Run resolver twice (raw-dict path accepts orchestrator format directly)
    resolver = LocalAssetResolver()

    try:
        results_1 = resolver.resolve(manifest)
        results_2 = resolver.resolve(manifest)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Resolver raised an exception: {exc}", file=sys.stderr)
        sys.exit(1)

    # 4. Assert deterministic output
    dump_1 = json.dumps([r.model_dump() for r in results_1], sort_keys=True)
    dump_2 = json.dumps([r.model_dump() for r in results_2], sort_keys=True)

    if dump_1 != dump_2:
        print(
            "ERROR: Non-deterministic output — resolver produced different results "
            "on two consecutive runs.",
            file=sys.stderr,
        )
        sys.exit(1)

    # 4b. Strict mode: reject placeholders (missing local assets)
    if strict:
        for r in results_1:
            if r.is_placeholder:
                print(
                    f"ERROR: invalid license for local asset {r.asset_id}",
                    file=sys.stderr,
                )
                sys.exit(1)

    # 5. Write AssetManifest.media.json (envelope format per AssetManifest.media.v1.json)
    output_path = run_dir / "AssetManifest.media.json"
    envelope = {
        "schema_id": "AssetManifest.media",
        "schema_version": "1.0.0",
        "manifest_id": manifest.get("manifest_id", ""),
        "project_id": manifest.get("project_id", ""),
        "producer": "media/verify_media_integration.py",
        "generated_at": "1970-01-01T00:00:00Z",
        "items": [r.model_dump() for r in results_1],
    }
    # 5b. Validate output envelope against contract before writing
    try:
        jsonschema.validate(instance=envelope, schema=_SCHEMA_OUT)
    except jsonschema.ValidationError as exc:
        print(
            f"ERROR: output envelope does not conform to AssetManifest.media.v1.json: {exc.message}",
            file=sys.stderr,
        )
        sys.exit(1)

    output_path.write_text(
        json.dumps(envelope, indent=2),
        encoding="utf-8",
    )

    # 6. Print summary
    total = len(results_1)
    placeholders = sum(1 for r in results_1 if r.is_placeholder)
    print(f"OK: {total} assets; {placeholders} placeholders")


if __name__ == "__main__":
    main()
