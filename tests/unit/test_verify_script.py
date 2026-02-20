"""End-to-end subprocess tests for scripts/verify_media_integration.py.

Covers both normal mode and --strict mode by running the script as a real
subprocess so stdout, stderr, and returncode are captured naturally.
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


def _write_asset(root: Path, subdir: str, filename: str, content: bytes = b"x") -> Path:
    """Create a dummy asset file under *root/subdir/filename*."""
    d = root / subdir
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    p.write_bytes(content)
    return p


def _write_manifest(run_dir: Path, manifest_dict: dict) -> None:
    """Write *manifest_dict* as JSON to *run_dir/AssetManifest.json*."""
    (run_dir / "AssetManifest.json").write_text(
        json.dumps(manifest_dict), encoding="utf-8"
    )


def _run(
    tmp_path: Path,
    extra_args: tuple = (),
    strict: bool = False,
) -> subprocess.CompletedProcess:
    """Invoke the verify script as a subprocess with the test environment."""
    env = {
        **os.environ,
        "LOCAL_ASSETS_ROOT": str(tmp_path),
        "RUN_DIR": str(tmp_path),
    }
    cmd = [sys.executable, str(SCRIPT)]
    if strict:
        cmd.append("--strict")
    cmd.extend(extra_args)
    return subprocess.run(cmd, env=env, capture_output=True, text=True)


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


# ---------------------------------------------------------------------------
# Test 1 — Normal mode: all assets found → OK summary
# ---------------------------------------------------------------------------


def test_normal_ok_summary_all_found(tmp_path: Path) -> None:
    """Normal mode with all assets present returns exit 0 and the expected summary."""
    _write_asset(tmp_path, "characters", "hero.png")
    manifest = _make_manifest(
        character_packs=[{"asset_id": "hero", "license_type": "proprietary_cleared"}]
    )
    _write_manifest(tmp_path, manifest)

    result = _run(tmp_path)

    assert result.returncode == 0
    assert result.stdout.strip() == "OK: 1 assets; 0 placeholders"


# ---------------------------------------------------------------------------
# Test 2 — Normal mode: mix of found + placeholder → OK summary
# ---------------------------------------------------------------------------


def test_normal_ok_summary_with_placeholder(tmp_path: Path) -> None:
    """Normal mode with one found asset and one missing asset returns exit 0."""
    _write_asset(tmp_path, "characters", "hero.png")
    manifest = _make_manifest(
        character_packs=[
            {"asset_id": "hero", "license_type": "proprietary_cleared"},
            {"asset_id": "ghost"},  # no file → placeholder
        ]
    )
    _write_manifest(tmp_path, manifest)

    result = _run(tmp_path)

    assert result.returncode == 0
    # structlog may emit warnings to stdout for the missing asset; check the final line.
    assert result.stdout.strip().splitlines()[-1] == "OK: 2 assets; 1 placeholders"


# ---------------------------------------------------------------------------
# Test 3 — Output file bytes are identical across two runs
# ---------------------------------------------------------------------------


def test_output_file_bytes_identical_across_runs(tmp_path: Path) -> None:
    """Running the script twice on the same manifest produces byte-identical output."""
    _write_asset(tmp_path, "characters", "hero.png")
    manifest = _make_manifest(
        character_packs=[{"asset_id": "hero", "license_type": "proprietary_cleared"}]
    )
    _write_manifest(tmp_path, manifest)

    result1 = _run(tmp_path)
    assert result1.returncode == 0

    bytes_run1 = (tmp_path / "AssetManifest.media.json").read_bytes()

    result2 = _run(tmp_path)
    assert result2.returncode == 0

    bytes_run2 = (tmp_path / "AssetManifest.media.json").read_bytes()

    assert bytes_run1 == bytes_run2


# ---------------------------------------------------------------------------
# Test 4 — Strict mode: placeholder present → exit 1 with exact error
# ---------------------------------------------------------------------------


def test_strict_mode_placeholder_fails_exact_error(tmp_path: Path) -> None:
    """Strict mode exits 1 and prints the exact error message for a placeholder asset."""
    manifest = _make_manifest(
        character_packs=[{"asset_id": "ghost"}]  # no file → placeholder
    )
    _write_manifest(tmp_path, manifest)

    result = _run(tmp_path, strict=True)

    assert result.returncode == 1
    assert "ERROR: invalid license for local asset ghost" in result.stderr


# ---------------------------------------------------------------------------
# Test 5 — Strict mode: all assets found → exit 0
# ---------------------------------------------------------------------------


def test_strict_mode_all_found_ok(tmp_path: Path) -> None:
    """Strict mode passes normally when all assets are resolved to real files."""
    _write_asset(tmp_path, "characters", "hero.png")
    manifest = _make_manifest(
        character_packs=[{"asset_id": "hero", "license_type": "proprietary_cleared"}]
    )
    _write_manifest(tmp_path, manifest)

    result = _run(tmp_path, strict=True)

    assert result.returncode == 0
    assert result.stdout.strip() == "OK: 1 assets; 0 placeholders"


# ---------------------------------------------------------------------------
# Test 6 — Missing RUN_DIR env var → exit 2
# ---------------------------------------------------------------------------


def test_missing_run_dir_env_exits_2(tmp_path: Path) -> None:
    """Script exits 2 when the RUN_DIR environment variable is not set."""
    env = {**os.environ, "LOCAL_ASSETS_ROOT": str(tmp_path)}
    env.pop("RUN_DIR", None)  # ensure RUN_DIR is absent

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2


# ---------------------------------------------------------------------------
# Test 7 — RUN_DIR set but AssetManifest.json absent → exit 2
# ---------------------------------------------------------------------------


def test_missing_manifest_json_exits_2(tmp_path: Path) -> None:
    """Script exits 2 when RUN_DIR is set but AssetManifest.json does not exist."""
    # Do NOT write AssetManifest.json — tmp_path exists but is empty.
    result = _run(tmp_path)

    assert result.returncode == 2
