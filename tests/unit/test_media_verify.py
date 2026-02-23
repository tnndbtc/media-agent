"""End-to-end subprocess tests for scripts/media.py verify command.

Covers the full `media verify` CLI including both normal and strict modes,
missing RUN_DIR handling, byte-identical output across rounds, and the
mismatch (diverging bytes) failure path.
"""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/media.py"


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


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    """Invoke `media.py verify` as a subprocess with the test environment."""
    env = {
        **os.environ,
        "LOCAL_ASSETS_ROOT": str(tmp_path),
        "RUN_DIR": str(tmp_path),
    }
    return subprocess.run(
        [sys.executable, str(SCRIPT), "verify"],
        env=env,
        capture_output=True,
        text=True,
    )


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


# ---------------------------------------------------------------------------
# Test 1 — All assets found → exit 0, "OK: media verified"
# ---------------------------------------------------------------------------


def test_verify_ok_all_found(tmp_path: Path) -> None:
    """media verify exits 0 and prints 'OK: media verified' when all assets are present."""
    _write_asset(tmp_path, "characters", "hero.png")
    manifest = _make_manifest(
        character_packs=[{"asset_id": "hero", "license_type": "proprietary_cleared"}]
    )
    _write_manifest(tmp_path, manifest)

    result = _run(tmp_path)

    assert result.returncode == 0
    assert result.stdout.strip() == "OK: media verified"


# ---------------------------------------------------------------------------
# Test 2 — Placeholder present → strict mode fails → exit 1
# ---------------------------------------------------------------------------


def test_verify_placeholder_strict_fails(tmp_path: Path) -> None:
    """media verify exits 1 when a placeholder asset fails strict mode."""
    manifest = _make_manifest(
        character_packs=[{"asset_id": "ghost", "license_type": "proprietary_cleared"}]  # no file → placeholder
    )
    _write_manifest(tmp_path, manifest)

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "ERROR: media verification failed" in result.stderr


# ---------------------------------------------------------------------------
# Test 3 — Missing RUN_DIR → exit 1
# ---------------------------------------------------------------------------


def test_verify_missing_run_dir_fails(tmp_path: Path) -> None:
    """media verify exits 1 when RUN_DIR is not set."""
    env = {**os.environ, "LOCAL_ASSETS_ROOT": str(tmp_path)}
    env.pop("RUN_DIR", None)  # ensure RUN_DIR is absent

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "verify"],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "ERROR: media verification failed" in result.stderr


# ---------------------------------------------------------------------------
# Test 4 — Output bytes identical across two full runs
# ---------------------------------------------------------------------------


def test_verify_output_bytes_identical_across_rounds(tmp_path: Path) -> None:
    """Running media verify twice produces byte-identical AssetManifest.media.json."""
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
# Test 5 — Bytes differ between rounds → exit 1, correct error message
# ---------------------------------------------------------------------------


def test_verify_mismatch_exits_1(tmp_path: Path) -> None:
    """cmd_verify exits 1 when AssetManifest.media.json bytes differ between rounds.

    Patches _run_verify so that both rounds succeed but the manifest file is
    written with different content on round 2 (calls 3-4), triggering the
    bytes_1 != bytes_2 branch.
    """
    # Load the media module fresh under a unique name to avoid import caching
    spec = importlib.util.spec_from_file_location("media_mismatch", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    call_n = {"n": 0}

    def fake_run_verify(strict: bool = False) -> bool:
        call_n["n"] += 1
        # Round 1 (calls 1-2): write one payload; Round 2 (calls 3-4): write another.
        content = b"bytes-round-1" if call_n["n"] <= 2 else b"bytes-round-2"
        (tmp_path / "AssetManifest.media.json").write_bytes(content)
        return True

    stderr_buf = io.StringIO()
    with (
        mock.patch.object(mod, "_run_verify", side_effect=fake_run_verify),
        mock.patch.dict(os.environ, {"RUN_DIR": str(tmp_path)}),
        contextlib.redirect_stderr(stderr_buf),
    ):
        rc = mod.cmd_verify()

    assert rc == 1
    assert "ERROR: media verification failed" in stderr_buf.getvalue()
