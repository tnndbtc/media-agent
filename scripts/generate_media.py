#!/usr/bin/env python3
"""Resolve an AssetManifest and write AssetManifest.media.json.

Usage:
    python scripts/generate_media.py \\
        --input  /path/to/AssetManifest.json \\
        --output /path/to/AssetManifest.media.json

Exit codes:
    0  — resolved successfully
    1  — resolver error or invalid input
    2  — bad arguments / input file not found
"""

import argparse
import json
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
    parser.add_argument(
        "--input", "-i",
        required=True,
        metavar="PATH",
        help="Path to AssetManifest.json produced by the orchestrator.",
    )
    parser.add_argument(
        "--output", "-o",
        required=True,
        metavar="PATH",
        help="Path to write the resolved AssetManifest.media.json.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any resolved asset is a placeholder (missing from library).",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    # 1. Validate input path
    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}", file=sys.stderr)
        sys.exit(2)

    # 2. Load manifest
    try:
        manifest = json.loads(input_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: failed to load {input_path}: {exc}", file=sys.stderr)
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

    # 3. Resolve
    resolver = LocalAssetResolver()
    try:
        results = resolver.resolve(manifest)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Resolver raised an exception: {exc}", file=sys.stderr)
        sys.exit(1)

    # 4. Strict mode: reject placeholders
    if args.strict:
        for r in results:
            if r.is_placeholder:
                print(
                    f"ERROR: placeholder asset {r.asset_id} — missing from library.",
                    file=sys.stderr,
                )
                sys.exit(1)

    # 5. Write output (envelope format per AssetManifest.media.v1.json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "schema_id": "AssetManifest.media",
        "schema_version": "1.0.0",
        "manifest_id": manifest.get("manifest_id", ""),
        "project_id": manifest.get("project_id", ""),
        "producer": "media/generate_media.py",
        "generated_at": "1970-01-01T00:00:00Z",
        "items": [r.model_dump() for r in results],
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

    # 6. Summary
    total = len(results)
    placeholders = sum(1 for r in results if r.is_placeholder)
    print(f"OK: {total} assets; {placeholders} placeholders → {output_path}")


if __name__ == "__main__":
    main()
