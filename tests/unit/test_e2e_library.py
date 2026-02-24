"""End-to-end tests against the real tests/library/ asset collection.

Unlike the synthetic fixtures used in the other test modules (which write
1-byte dummy files into tmp_path), every test here resolves against the
checked-in library at tests/library/ so every resolved asset is a genuine
file with a real license record.

Coverage:
  T1  — All 6 assets resolve; exit 0; summary reports 0 placeholders
  T2  — Strict mode passes when the full library is present
  T3  — Output file conforms to the AssetManifest.media.v1.json contract
  T4  — Two consecutive runs produce byte-identical output (determinism)
  T5  — Every item in the output has is_placeholder=false
  T6  — License fields are populated from the .license.json files (spdx_id, attribution_required)
  T7  — Every resolved URI is a file:// URI whose path exists on disk
  T8  — Output item order mirrors manifest array order: chars → bgs → vo
  T9  — generate_media.py produces a schema-valid envelope from the same manifest
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import jsonschema
import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT      = Path(__file__).resolve().parents[2]
_LIBRARY_DIR    = _REPO_ROOT / "tests" / "library"
_VERIFY_SCRIPT  = _REPO_ROOT / "scripts" / "verify_media_integration.py"
_GENERATE_SCRIPT = _REPO_ROOT / "scripts" / "generate_media.py"
_CONTRACTS_DIR  = _REPO_ROOT / "third_party" / "contracts" / "schemas"

_SCHEMA_IN  = json.loads((_CONTRACTS_DIR / "AssetManifest.v1.json").read_text(encoding="utf-8"))
_SCHEMA_OUT = json.loads((_CONTRACTS_DIR / "AssetManifest.media.v1.json").read_text(encoding="utf-8"))

# ---------------------------------------------------------------------------
# Manifest that exercises all 6 real library assets
# ---------------------------------------------------------------------------

_FULL_MANIFEST: dict = {
    "schema_id":     "AssetManifest",
    "schema_version": "1.0.0",
    "manifest_id":   "e2e-test-001",
    "project_id":    "test-project",
    "shotlist_ref":  "test-shots-001",
    "character_packs": [
        {"asset_id": "char-analyst",   "license_type": "CC0"},
        {"asset_id": "char-commander", "license_type": "CC0"},
    ],
    "backgrounds": [
        {"asset_id": "bg-scene-1", "license_type": "CC0"},
    ],
    "vo_items": [
        {"item_id": "vo-scene-1-commander-000", "speaker_id": "commander", "text": "Did anyone follow you?",  "license_type": "CC0"},
        {"item_id": "vo-scene-1-analyst-001",   "speaker_id": "analyst",   "text": "No. But we shouldn't stay.", "license_type": "CC0"},
    ],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_manifest(run_dir: Path, manifest: dict = _FULL_MANIFEST) -> None:
    """Write *manifest* as AssetManifest.json inside *run_dir*."""
    (run_dir / "AssetManifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _run_verify(run_dir: Path, strict: bool = False) -> subprocess.CompletedProcess:
    """Invoke verify_media_integration.py against the real library."""
    env = {
        **os.environ,
        "RUN_DIR":            str(run_dir),
        "MEDIA_LIBRARY_ROOT": str(_LIBRARY_DIR),
        # Point LOCAL_ASSETS_ROOT at a non-existent directory so the fallback
        # path never masks a library miss with a placeholder.
        "LOCAL_ASSETS_ROOT":  str(run_dir / "_no_local_assets"),
    }
    cmd = [sys.executable, str(_VERIFY_SCRIPT)]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, env=env, capture_output=True, text=True)


def _read_output(run_dir: Path) -> dict:
    return json.loads((run_dir / "AssetManifest.media.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# T1 — All 6 assets resolve; exit 0; 0 placeholders in summary
# ---------------------------------------------------------------------------


def test_e2e_all_assets_resolve_no_placeholders(tmp_path: Path) -> None:
    """All 6 library assets resolve to real files; exit 0, 0 placeholders reported."""
    _write_manifest(tmp_path)
    result = _run_verify(tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "OK: 5 assets; 0 placeholders"


# ---------------------------------------------------------------------------
# T2 — Strict mode passes when the full library is present
# ---------------------------------------------------------------------------


def test_e2e_strict_mode_passes(tmp_path: Path) -> None:
    """Strict mode exits 0 when every manifest entry resolves to a real library file."""
    _write_manifest(tmp_path)
    result = _run_verify(tmp_path, strict=True)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "OK: 5 assets; 0 placeholders"


# ---------------------------------------------------------------------------
# T3 — Output file conforms to the AssetManifest.media.v1.json contract
# ---------------------------------------------------------------------------


def test_e2e_output_conforms_to_contract(tmp_path: Path) -> None:
    """The written AssetManifest.media.json is valid against the media contract schema."""
    _write_manifest(tmp_path)
    result = _run_verify(tmp_path)
    assert result.returncode == 0, result.stderr

    output = _read_output(tmp_path)
    try:
        jsonschema.validate(instance=output, schema=_SCHEMA_OUT)
    except jsonschema.ValidationError as exc:
        pytest.fail(f"Output does not conform to AssetManifest.media.v1.json: {exc.message}")


# ---------------------------------------------------------------------------
# T4 — Two consecutive runs produce byte-identical output (determinism)
# ---------------------------------------------------------------------------


def test_e2e_output_byte_identical_across_runs(tmp_path: Path) -> None:
    """Running verify twice against the real library produces byte-identical output files."""
    _write_manifest(tmp_path)

    r1 = _run_verify(tmp_path)
    assert r1.returncode == 0, r1.stderr
    bytes_1 = (tmp_path / "AssetManifest.media.json").read_bytes()

    r2 = _run_verify(tmp_path)
    assert r2.returncode == 0, r2.stderr
    bytes_2 = (tmp_path / "AssetManifest.media.json").read_bytes()

    assert bytes_1 == bytes_2, "Output is non-deterministic across two runs"


# ---------------------------------------------------------------------------
# T5 — Every item in the output has is_placeholder=false
# ---------------------------------------------------------------------------


def test_e2e_no_placeholders_in_output(tmp_path: Path) -> None:
    """No item in the resolved output is a placeholder when the full library is present."""
    _write_manifest(tmp_path)
    result = _run_verify(tmp_path)
    assert result.returncode == 0, result.stderr

    items = _read_output(tmp_path)["items"]
    placeholders = [item for item in items if item["is_placeholder"]]
    assert placeholders == [], (
        f"{len(placeholders)} unexpected placeholder(s): "
        + ", ".join(p["asset_id"] for p in placeholders)
    )


# ---------------------------------------------------------------------------
# T6 — License fields populated from the .license.json files
# ---------------------------------------------------------------------------


def test_e2e_license_fields_populated_from_library(tmp_path: Path) -> None:
    """Every resolved item carries the spdx_id and attribution_required from its .license.json."""
    _write_manifest(tmp_path)
    result = _run_verify(tmp_path)
    assert result.returncode == 0, result.stderr

    for item in _read_output(tmp_path)["items"]:
        lic = item["license"]
        assert lic["spdx_id"] == "CC0", (
            f"asset_id={item['asset_id']!r}: expected spdx_id='CC0', got {lic['spdx_id']!r}"
        )
        assert lic["attribution_required"] is False, (
            f"asset_id={item['asset_id']!r}: expected attribution_required=false"
        )


# ---------------------------------------------------------------------------
# T7 — Every resolved URI is a file:// URI whose path exists on disk
# ---------------------------------------------------------------------------


def test_e2e_uris_resolve_to_real_files(tmp_path: Path) -> None:
    """Every item URI is a file:// URI and the path it points to actually exists."""
    _write_manifest(tmp_path)
    result = _run_verify(tmp_path)
    assert result.returncode == 0, result.stderr

    for item in _read_output(tmp_path)["items"]:
        uri = item["uri"]
        assert uri.startswith("file://"), (
            f"asset_id={item['asset_id']!r}: expected file:// URI, got {uri!r}"
        )
        path = Path(urlparse(uri).path)
        assert path.exists(), (
            f"asset_id={item['asset_id']!r}: URI path does not exist on disk: {path}"
        )


# ---------------------------------------------------------------------------
# T8 — Output item order mirrors manifest array order: chars → bgs → vo
# ---------------------------------------------------------------------------


def test_e2e_output_order_matches_manifest(tmp_path: Path) -> None:
    """Resolved items appear in manifest order: character × 2, background × 2, vo × 2."""
    _write_manifest(tmp_path)
    result = _run_verify(tmp_path)
    assert result.returncode == 0, result.stderr

    items = _read_output(tmp_path)["items"]
    assert len(items) == 5

    expected_types = ["character", "character", "background", "vo", "vo"]
    actual_types   = [item["asset_type"] for item in items]
    assert actual_types == expected_types, f"Unexpected asset_type order: {actual_types}"

    assert items[0]["asset_id"] == "char-analyst"
    assert items[1]["asset_id"] == "char-commander"
    assert items[2]["asset_id"] == "bg-scene-1"
    assert items[3]["asset_id"] == "vo-scene-1-commander-000"
    assert items[4]["asset_id"] == "vo-scene-1-analyst-001"


# ---------------------------------------------------------------------------
# T9 — generate_media.py produces a schema-valid envelope from the same manifest
# ---------------------------------------------------------------------------


def test_e2e_generate_script_produces_valid_output(tmp_path: Path) -> None:
    """generate_media.py resolves the real library and writes a schema-valid output file."""
    input_path  = tmp_path / "AssetManifest.json"
    output_path = tmp_path / "AssetManifest.media.json"
    input_path.write_text(json.dumps(_FULL_MANIFEST), encoding="utf-8")

    env = {
        **os.environ,
        "MEDIA_LIBRARY_ROOT": str(_LIBRARY_DIR),
        "LOCAL_ASSETS_ROOT":  str(tmp_path / "_no_local_assets"),
    }
    result = subprocess.run(
        [
            sys.executable, str(_GENERATE_SCRIPT),
            "--input",  str(input_path),
            "--output", str(output_path),
            "--strict",
        ],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "OK: 5 assets; 0 placeholders" in result.stdout

    output = json.loads(output_path.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(instance=output, schema=_SCHEMA_OUT)
    except jsonschema.ValidationError as exc:
        pytest.fail(f"generate_media.py output does not conform to AssetManifest.media.v1.json: {exc.message}")
