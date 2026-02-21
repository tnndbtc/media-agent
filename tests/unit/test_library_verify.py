"""End-to-end subprocess tests for the MEDIA_LIBRARY_ROOT resolution path.

Covers library asset discovery, license enforcement, and deterministic output
by running verify_media_integration.py as a real subprocess, mirroring the
pattern established in test_verify_script.py.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/verify_media_integration.py"


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
    """Build a minimal canonical AssetManifest dict."""
    return {
        "schema_version": "1",
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
# T1 — Library asset with license present → OK summary
# ---------------------------------------------------------------------------


def test_library_asset_with_license_ok(tmp_path: Path) -> None:
    """Library asset with a valid CC0 license file resolves to exit 0 and OK summary."""
    lib_root = tmp_path / "lib"
    _write_library_asset(lib_root, "hero.png")
    _write_license(lib_root, "hero")

    manifest = _make_manifest(
        character_packs=[{"asset_id": "hero", "license_type": "CC0"}]
    )
    (tmp_path / "AssetManifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    result = _run_library(tmp_path, lib_root)

    assert result.returncode == 0
    assert result.stdout.strip() == "OK: 1 assets; 0 placeholders"


# ---------------------------------------------------------------------------
# T2 — Library asset present but license file missing → exit 1 with error
# ---------------------------------------------------------------------------


def test_library_asset_missing_license_error(tmp_path: Path) -> None:
    """Library asset without a license file causes exit 1 with a descriptive error."""
    lib_root = tmp_path / "lib"
    _write_library_asset(lib_root, "hero.png")
    # Intentionally omit the license file.

    manifest = _make_manifest(
        character_packs=[{"asset_id": "hero"}]
    )
    (tmp_path / "AssetManifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    result = _run_library(tmp_path, lib_root)

    assert result.returncode == 1
    # The resolver raises ValueError whose message is wrapped by the script as:
    # "ERROR: Resolver raised an exception: ERROR: missing license file for …"
    assert "ERROR: missing license file for local asset hero" in result.stderr


# ---------------------------------------------------------------------------
# T3 — Two successive runs produce byte-identical AssetManifest.media.json
# ---------------------------------------------------------------------------


def test_library_two_runs_bytes_identical(tmp_path: Path) -> None:
    """Running the verify script twice on the same library manifest is byte-identical."""
    lib_root = tmp_path / "lib"
    _write_library_asset(lib_root, "hero.png")
    _write_license(lib_root, "hero")

    manifest = _make_manifest(
        character_packs=[{"asset_id": "hero", "license_type": "CC0"}]
    )
    (tmp_path / "AssetManifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    result1 = _run_library(tmp_path, lib_root)
    assert result1.returncode == 0
    bytes_run1 = (tmp_path / "AssetManifest.media.json").read_bytes()

    result2 = _run_library(tmp_path, lib_root)
    assert result2.returncode == 0
    bytes_run2 = (tmp_path / "AssetManifest.media.json").read_bytes()

    assert bytes_run1 == bytes_run2
