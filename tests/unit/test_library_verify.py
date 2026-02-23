"""End-to-end subprocess tests for the MEDIA_LIBRARY_ROOT resolution path.

Covers:
  - Library asset discovery and license enforcement
  - Input manifest validated against AssetManifest.v1.json before every run
  - Output file validated against AssetManifest.media.v1.json after every
    successful run
  - Deterministic (byte-identical) output on consecutive runs

Tests run verify_media_integration.py as a real subprocess, mirroring the
pattern established in test_verify_script.py.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import jsonschema

# ---------------------------------------------------------------------------
# Contract schemas — loaded once at import time
# ---------------------------------------------------------------------------

_CONTRACTS_DIR = (
    Path(__file__).resolve().parents[2] / "third_party" / "contracts" / "schemas"
)
_SCHEMA_IN: dict = json.loads(
    (_CONTRACTS_DIR / "AssetManifest.v1.json").read_text(encoding="utf-8")
)
_SCHEMA_OUT: dict = json.loads(
    (_CONTRACTS_DIR / "AssetManifest.media.v1.json").read_text(encoding="utf-8")
)

# ---------------------------------------------------------------------------
# Script under test
# ---------------------------------------------------------------------------

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/verify_media_integration.py"


# ---------------------------------------------------------------------------
# Schema-validation helpers
# ---------------------------------------------------------------------------


def _assert_valid_input(manifest: dict) -> None:
    """Assert *manifest* conforms to AssetManifest.v1.json.

    Raises AssertionError with a human-readable message on failure so that
    pytest output is easy to read.
    """
    try:
        jsonschema.validate(instance=manifest, schema=_SCHEMA_IN)
    except jsonschema.ValidationError as exc:
        raise AssertionError(
            f"Input manifest does not conform to AssetManifest.v1.json:\n  {exc.message}"
        ) from exc


def _assert_valid_output(output_path: Path) -> None:
    """Assert the JSON file at *output_path* conforms to AssetManifest.media.v1.json.

    Raises AssertionError with a human-readable message on failure.
    """
    data = json.loads(output_path.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(instance=data, schema=_SCHEMA_OUT)
    except jsonschema.ValidationError as exc:
        raise AssertionError(
            f"Output file does not conform to AssetManifest.media.v1.json:\n  {exc.message}"
        ) from exc


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_library_asset(lib_root: Path, filename: str, content: bytes = b"x") -> Path:
    """Write lib_root/images/<filename>."""
    d = lib_root / "images"
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    p.write_bytes(content)
    return p


def _write_license(lib_root: Path, asset_id: str, data: dict | None = None) -> Path:
    """Write lib_root/licenses/<asset_id>.license.json."""
    d = lib_root / "licenses"
    d.mkdir(parents=True, exist_ok=True)
    payload = data or {"spdx_id": "CC0", "attribution_required": False, "text": ""}
    p = d / f"{asset_id}.license.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _make_manifest(
    character_packs: list | None = None,
    backgrounds: list | None = None,
    vo_items: list | None = None,
) -> dict:
    """Build a minimal canonical AssetManifest dict (contract-valid per AssetManifest.v1.json)."""
    return {
        "schema_id": "AssetManifest",
        "schema_version": "1.0.0",
        "manifest_id": "test-manifest",
        "project_id": "proj-001",
        "shotlist_ref": "shots-001",
        "character_packs": character_packs or [],
        "backgrounds": backgrounds or [],
        "vo_items": vo_items or [],
    }


def _run_library(
    tmp_path: Path,
    lib_root: Path,
    strict: bool = False,
) -> subprocess.CompletedProcess:
    """Invoke the verify script with MEDIA_LIBRARY_ROOT set.

    LOCAL_ASSETS_ROOT is also set (to tmp_path) to suppress fallback-path
    log noise that would otherwise appear in stdout.
    """
    env = {
        **os.environ,
        "RUN_DIR": str(tmp_path),
        "LOCAL_ASSETS_ROOT": str(tmp_path),  # suppress fallback log noise
        "MEDIA_LIBRARY_ROOT": str(lib_root),
    }
    cmd = [sys.executable, str(SCRIPT)]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, env=env, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# T1 — Library asset with license present → OK summary, both contracts pass
# ---------------------------------------------------------------------------


def test_library_asset_with_license_ok(tmp_path: Path) -> None:
    """Library asset with a valid CC0 license file resolves to exit 0 and OK summary.

    Validates:
      - Input manifest against AssetManifest.v1.json  (pre-run)
      - Output file   against AssetManifest.media.v1.json (post-run)
    """
    lib_root = tmp_path / "lib"
    _write_library_asset(lib_root, "hero.png")
    _write_license(lib_root, "hero")

    manifest = _make_manifest(
        character_packs=[{"asset_id": "hero", "license_type": "CC0"}]
    )
    (tmp_path / "AssetManifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    # Contract check: input must conform before we even call the script.
    _assert_valid_input(manifest)

    result = _run_library(tmp_path, lib_root)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK: 1 assets; 0 placeholders"

    # Contract check: output must conform to AssetManifest.media.v1.json.
    _assert_valid_output(tmp_path / "AssetManifest.media.json")


# ---------------------------------------------------------------------------
# T2 — Library asset present but license file missing → exit 1, valid input
# ---------------------------------------------------------------------------


def test_library_asset_missing_license_error(tmp_path: Path) -> None:
    """Library asset without a license file causes exit 1 with a descriptive error.

    The input manifest is contract-valid (license_type present), so the failure
    is detected by the resolver (missing license FILE on disk), not by schema
    validation.  No output file is written on failure.
    """
    lib_root = tmp_path / "lib"
    _write_library_asset(lib_root, "hero.png")
    # Intentionally omit the license FILE — the manifest entry is still valid.

    manifest = _make_manifest(
        character_packs=[{"asset_id": "hero", "license_type": "CC0"}]
    )
    (tmp_path / "AssetManifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    # Contract check: input is valid even though the runtime will fail.
    _assert_valid_input(manifest)

    result = _run_library(tmp_path, lib_root)

    assert result.returncode == 1
    # The resolver raises ValueError whose message is wrapped by the script as:
    # "ERROR: Resolver raised an exception: ERROR: missing license file for …"
    assert "ERROR: missing license file for local asset hero" in result.stderr


# ---------------------------------------------------------------------------
# T3 — Two successive runs produce byte-identical AssetManifest.media.json
# ---------------------------------------------------------------------------


def test_library_two_runs_bytes_identical(tmp_path: Path) -> None:
    """Running the verify script twice on the same library manifest is byte-identical.

    Also validates that the final output conforms to AssetManifest.media.v1.json.
    (Both runs produce the same bytes, so one schema check is sufficient.)
    """
    lib_root = tmp_path / "lib"
    _write_library_asset(lib_root, "hero.png")
    _write_license(lib_root, "hero")

    manifest = _make_manifest(
        character_packs=[{"asset_id": "hero", "license_type": "CC0"}]
    )
    (tmp_path / "AssetManifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    # Contract check: input is valid before any run.
    _assert_valid_input(manifest)

    result1 = _run_library(tmp_path, lib_root)
    assert result1.returncode == 0, result1.stderr
    bytes_run1 = (tmp_path / "AssetManifest.media.json").read_bytes()

    result2 = _run_library(tmp_path, lib_root)
    assert result2.returncode == 0, result2.stderr
    bytes_run2 = (tmp_path / "AssetManifest.media.json").read_bytes()

    assert bytes_run1 == bytes_run2

    # Contract check: output is schema-valid (both runs are identical, one check suffices).
    _assert_valid_output(tmp_path / "AssetManifest.media.json")
