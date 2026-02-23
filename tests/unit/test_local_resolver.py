"""Unit tests for Phase 0 LocalAssetResolver.

Covers:
  1. Deterministic resolution — same manifest + same assets dir → identical output.
  2. Found local asset → correct file:// URI and metadata.
  3. Missing asset → placeholder with correct flags.
  4. Extension preference — png preferred over jpg when both present.
  5. Unknown license_type → rights_warning populated; no exception raised.

All tests are synchronous and use only pytest + tmp_path (no network, no Redis,
no OpenAI).
"""

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from models.resolution import AssetLicense, AssetMetadata, AssetSource, ResolvedAsset
from resolvers.local import LocalAssetResolver
from rights.license_validator import LicenseValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_asset(root: Path, subdir: str, filename: str, content: bytes = b"x") -> Path:
    """Create a dummy asset file under *root/subdir/filename*."""
    d = root / subdir
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    p.write_bytes(content)
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


# ---------------------------------------------------------------------------
# Test 1 — Deterministic resolution
# ---------------------------------------------------------------------------


def test_resolve_is_deterministic(tmp_path: Path) -> None:
    """Same manifest + same assets directory → identical list[ResolvedAsset] each call."""
    _write_asset(tmp_path, "characters", "hero.png")
    _write_asset(tmp_path, "backgrounds", "office.jpg")

    manifest = _make_manifest(
        character_packs=[{"asset_id": "hero", "license_type": "proprietary_cleared"}],
        backgrounds=[{"asset_id": "office", "license_type": "proprietary_cleared"}],
        vo_items=[{"item_id": "vo-001", "speaker_id": "narrator", "text": "Hello", "license_type": "proprietary_cleared"}],
    )

    resolver = LocalAssetResolver(assets_root=str(tmp_path))
    first = resolver.resolve(manifest)
    second = resolver.resolve(manifest)

    assert len(first) == len(second) == 3
    for a, b in zip(first, second):
        assert a.model_dump() == b.model_dump(), (
            f"Non-deterministic output for asset_id={a.asset_id}"
        )


# ---------------------------------------------------------------------------
# Test 2 — Found local asset → correct metadata
# ---------------------------------------------------------------------------


def test_found_asset_returns_file_uri_and_metadata(tmp_path: Path) -> None:
    """A present local file resolves to a file:// URI with proprietary_cleared metadata."""
    asset_path = _write_asset(tmp_path, "characters", "hero.png")

    manifest = _make_manifest(character_packs=[{"asset_id": "hero", "license_type": "proprietary_cleared"}])
    resolver = LocalAssetResolver(assets_root=str(tmp_path))
    results = resolver.resolve(manifest)

    assert len(results) == 1
    resolved = results[0]

    assert resolved.is_placeholder is False
    assert resolved.uri == asset_path.as_uri()
    assert resolved.metadata.license_type == "proprietary_cleared"
    assert resolved.metadata.provider_or_model == "local_library"
    assert resolved.metadata.retrieval_date == "1970-01-01T00:00:00Z"
    assert resolved.rights_warning == ""


# ---------------------------------------------------------------------------
# Test 3 — Missing asset → placeholder
# ---------------------------------------------------------------------------


def test_missing_asset_returns_placeholder(tmp_path: Path) -> None:
    """An asset with no matching local file produces a placeholder record."""
    manifest = _make_manifest(character_packs=[{"asset_id": "ghost"}])
    resolver = LocalAssetResolver(assets_root=str(tmp_path))
    results = resolver.resolve(manifest)

    assert len(results) == 1
    resolved = results[0]

    assert resolved.is_placeholder is True
    assert resolved.uri == "placeholder://character/ghost"
    assert resolved.metadata.license_type == "placeholder"
    assert resolved.metadata.provider_or_model == "placeholder_stub_v0"
    assert resolved.metadata.retrieval_date == "1970-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Test 4 — Extension preference (png > jpg)
# ---------------------------------------------------------------------------


def test_extension_preference_png_over_jpg(tmp_path: Path) -> None:
    """When both hero.jpg and hero.png exist, hero.png is chosen (png > jpg)."""
    _write_asset(tmp_path, "characters", "hero.jpg")
    _write_asset(tmp_path, "characters", "hero.png")

    manifest = _make_manifest(character_packs=[{"asset_id": "hero", "license_type": "proprietary_cleared"}])
    resolver = LocalAssetResolver(assets_root=str(tmp_path))
    results = resolver.resolve(manifest)

    assert len(results) == 1
    assert results[0].uri.endswith("hero.png"), (
        f"Expected hero.png to be preferred, got: {results[0].uri}"
    )


# ---------------------------------------------------------------------------
# Test 5 — Unknown license_type → rights_warning, no exception
# ---------------------------------------------------------------------------


def test_unknown_license_emits_warning_not_exception(tmp_path: Path) -> None:
    """An asset with an unknown license_type sets rights_warning but does not raise."""
    # Write a file so we get a non-placeholder resolved asset with our custom license.
    _write_asset(tmp_path, "backgrounds", "studio.png")

    # Provide an unrecognised license in the manifest entry.
    manifest = _make_manifest(
        backgrounds=[{"asset_id": "studio", "license_type": "MYSTERY_LICENSE"}]
    )
    resolver = LocalAssetResolver(assets_root=str(tmp_path))

    # Must not raise.
    results = resolver.resolve(manifest)

    assert len(results) == 1
    resolved = results[0]
    assert resolved.is_placeholder is False
    assert resolved.metadata.license_type == "MYSTERY_LICENSE"
    assert resolved.rights_warning != "", (
        "Expected a non-empty rights_warning for unknown license_type"
    )
    assert "MYSTERY_LICENSE" in resolved.rights_warning


def test_license_validator_known_types_return_empty_warning() -> None:
    """All allowed license types pass validation without a warning."""
    validator = LicenseValidator()
    for lt in ["proprietary_cleared", "CC0", "commercial_licensed", "generated_local", "placeholder"]:
        assert validator.validate(lt) == "", f"Unexpected warning for known type '{lt}'"


def test_license_validator_unknown_type_returns_warning_string() -> None:
    """An unknown license_type returns a non-empty warning string (no raise)."""
    validator = LicenseValidator()
    warning = validator.validate("UNKNOWN_TYPE")
    assert isinstance(warning, str)
    assert len(warning) > 0
    assert "UNKNOWN_TYPE" in warning


# ---------------------------------------------------------------------------
# Test — Output ordering: character_packs → backgrounds → vo_items
# ---------------------------------------------------------------------------


def test_output_order_follows_manifest_array_order(tmp_path: Path) -> None:
    """Resolved assets appear in manifest order: character_packs, backgrounds, vo_items."""
    _write_asset(tmp_path, "characters", "alice.png")
    _write_asset(tmp_path, "backgrounds", "forest.png")

    manifest = _make_manifest(
        character_packs=[{"asset_id": "alice", "license_type": "proprietary_cleared"}],
        backgrounds=[{"asset_id": "forest", "license_type": "proprietary_cleared"}],
        vo_items=[
            {"item_id": "line-01", "speaker_id": "alice", "text": "Hi", "license_type": "proprietary_cleared"},
            {"item_id": "line-02", "speaker_id": "alice", "text": "Bye", "license_type": "proprietary_cleared"},
        ],
    )
    resolver = LocalAssetResolver(assets_root=str(tmp_path))
    results = resolver.resolve(manifest)

    assert len(results) == 4
    assert results[0].asset_type == "character"
    assert results[1].asset_type == "background"
    assert results[2].asset_type == "vo"
    assert results[3].asset_type == "vo"
    assert results[2].asset_id == "line-01"
    assert results[3].asset_id == "line-02"


# ---------------------------------------------------------------------------
# Test — vo_items use existing license_type from manifest
# ---------------------------------------------------------------------------


def test_vo_item_preserves_manifest_license_type(tmp_path: Path) -> None:
    """vo_items already carry license_type in the manifest; resolver must honour it."""
    _write_asset(tmp_path, "vo", "line-01.wav")

    manifest = _make_manifest(
        vo_items=[
            {
                "item_id": "line-01",
                "speaker_id": "narrator",
                "text": "Hello world",
                "license_type": "CC0",
            }
        ]
    )
    resolver = LocalAssetResolver(assets_root=str(tmp_path))
    results = resolver.resolve(manifest)

    assert len(results) == 1
    assert results[0].metadata.license_type == "CC0"
    assert results[0].is_placeholder is False
    assert results[0].rights_warning == ""


# ---------------------------------------------------------------------------
# Integration test — orchestrator AssetManifest.json field names
# ---------------------------------------------------------------------------


def test_orchestrator_manifest_ids_resolve_to_file_uris(tmp_path: Path) -> None:
    """pack_id / bg_id / item_id from orchestrator manifest resolve to real files."""
    char_path = _write_asset(tmp_path, "characters", "hero-pack.png")
    bg_path   = _write_asset(tmp_path, "backgrounds", "rooftop.jpg")
    vo_path   = _write_asset(tmp_path, "vo", "line-01.wav")

    manifest = _make_manifest(
        character_packs=[{"pack_id": "hero-pack", "license_type": "proprietary_cleared"}],
        backgrounds=[{"bg_id": "rooftop", "license_type": "proprietary_cleared"}],
        vo_items=[{"item_id": "line-01", "speaker_id": "narrator",
                   "text": "Hello", "license_type": "proprietary_cleared"}],
    )

    resolver = LocalAssetResolver(assets_root=str(tmp_path))
    results = resolver.resolve(manifest)

    assert len(results) == 3

    char_r, bg_r, vo_r = results

    assert char_r.is_placeholder is False
    assert char_r.asset_type == "character"
    assert char_r.uri == char_path.as_uri()

    assert bg_r.is_placeholder is False
    assert bg_r.asset_type == "background"
    assert bg_r.uri == bg_path.as_uri()

    assert vo_r.is_placeholder is False
    assert vo_r.asset_type == "vo"
    assert vo_r.uri == vo_path.as_uri()


# ---------------------------------------------------------------------------
# Wave-1 tests — provenance metadata & deterministic placeholder URIs
# ---------------------------------------------------------------------------


def test_source_field_on_found_asset(tmp_path: Path) -> None:
    """A successfully resolved local file has source.type == 'local'."""
    _write_asset(tmp_path, "characters", "hero.png")

    manifest = _make_manifest(character_packs=[{"asset_id": "hero", "license_type": "proprietary_cleared"}])
    resolver = LocalAssetResolver(assets_root=str(tmp_path))
    results = resolver.resolve(manifest)

    assert len(results) == 1
    assert results[0].source.type == "local"


def test_source_field_on_placeholder(tmp_path: Path) -> None:
    """A placeholder asset (no local file) has source.type == 'generated_placeholder'."""
    manifest = _make_manifest(character_packs=[{"asset_id": "ghost"}])
    resolver = LocalAssetResolver(assets_root=str(tmp_path))
    results = resolver.resolve(manifest)

    assert len(results) == 1
    assert results[0].source.type == "generated_placeholder"


def test_license_field_defaults(tmp_path: Path) -> None:
    """Found asset gets spdx_id from manifest; placeholder defaults to NOASSERTION."""
    _write_asset(tmp_path, "characters", "hero.png")

    manifest = _make_manifest(
        character_packs=[
            {"asset_id": "hero", "license_type": "proprietary_cleared"},
            {"asset_id": "ghost"},   # missing → placeholder
        ]
    )
    resolver = LocalAssetResolver(assets_root=str(tmp_path))
    results = resolver.resolve(manifest)

    assert len(results) == 2
    # Found asset: spdx_id reflects the manifest license_type
    assert results[0].license.spdx_id == "proprietary_cleared"
    assert results[0].license.attribution_required is False
    assert results[0].license.text == ""
    # Placeholder: spdx_id stays at NOASSERTION
    assert results[1].license.spdx_id == "NOASSERTION"
    assert results[1].license.attribution_required is False
    assert results[1].license.text == ""


def test_placeholder_uri_sha256_deterministic(tmp_path: Path) -> None:
    """Resolving the same missing asset twice yields identical sha256-based URIs."""
    manifest = _make_manifest(character_packs=[{"asset_id": "missing-char"}])
    resolver = LocalAssetResolver(assets_root=str(tmp_path))

    first = resolver.resolve(manifest)[0]
    second = resolver.resolve(manifest)[0]

    assert first.uri == second.uri, "Placeholder URI must be deterministic"

    # URI must have the form placeholder://<type>/<normalized-id>
    assert first.uri == "placeholder://character/missing-char", (
        f"Unexpected placeholder URI format: {first.uri!r}"
    )


def test_uri_validator_rejects_http_https() -> None:
    """ResolvedAsset raises ValidationError when constructed with an http:// URI."""
    with pytest.raises(ValidationError):
        ResolvedAsset(
            asset_id="remote-asset",
            asset_type="character",
            uri="http://example.com/x.png",
            source=AssetSource(type="local"),
        )

    with pytest.raises(ValidationError):
        ResolvedAsset(
            asset_id="remote-asset",
            asset_type="character",
            uri="https://example.com/x.png",
            source=AssetSource(type="local"),
        )


# ---------------------------------------------------------------------------
# Wave-2 tests — license required for local assets + exact error messages
# ---------------------------------------------------------------------------


def test_wave2_missing_license_local_asset_raises(tmp_path: Path) -> None:
    """Resolving a found local file without license_type raises with the exact error."""
    _write_asset(tmp_path, "characters", "hero.png")

    manifest = _make_manifest(character_packs=[{"asset_id": "hero"}])
    resolver = LocalAssetResolver(assets_root=str(tmp_path))

    with pytest.raises(ValueError) as exc_info:
        resolver.resolve(manifest)

    assert str(exc_info.value) == "ERROR: invalid license for local asset hero"


def test_wave2_placeholder_allows_noassertion_license(tmp_path: Path) -> None:
    """A missing asset (placeholder) requires no license and has spdx_id == 'NOASSERTION'."""
    manifest = _make_manifest(character_packs=[{"asset_id": "ghost"}])
    resolver = LocalAssetResolver(assets_root=str(tmp_path))

    results = resolver.resolve(manifest)

    assert len(results) == 1
    assert results[0].is_placeholder is True
    assert results[0].license.spdx_id == "NOASSERTION"


def test_wave2_remote_uri_exact_error_message() -> None:
    """ResolvedAsset raises ValidationError with the exact Wave-2 error prefix for http://."""
    with pytest.raises(ValidationError) as exc_info:
        ResolvedAsset(
            asset_id="remote-asset",
            asset_type="character",
            uri="http://example.com/x.png",
            source=AssetSource(type="local"),
            metadata=AssetMetadata(license_type="proprietary_cleared"),
        )

    assert "ERROR: remote uri not allowed: http://example.com/x.png" in str(exc_info.value)


def test_wave2_two_run_json_bytes_identical(tmp_path: Path) -> None:
    """Resolving the same manifest twice yields byte-identical model_dump_json() output."""
    _write_asset(tmp_path, "characters", "hero.png")

    manifest = _make_manifest(
        character_packs=[
            {"asset_id": "hero", "license_type": "proprietary_cleared"},
            {"asset_id": "ghost"},   # missing → placeholder
        ]
    )
    resolver = LocalAssetResolver(assets_root=str(tmp_path))
    first = resolver.resolve(manifest)
    second = resolver.resolve(manifest)

    assert [r.model_dump_json() for r in first] == [r.model_dump_json() for r in second]


# ---------------------------------------------------------------------------
# Wave-3 tests — NOASSERTION guard + schema metadata fields
# ---------------------------------------------------------------------------


def test_wave3_noassertion_license_raises(tmp_path: Path) -> None:
    """Resolving a found local file with license_type='NOASSERTION' raises with the exact error."""
    _write_asset(tmp_path, "characters", "hero.png")

    manifest = _make_manifest(character_packs=[{"asset_id": "hero", "license_type": "NOASSERTION"}])
    resolver = LocalAssetResolver(assets_root=str(tmp_path))

    with pytest.raises(ValueError) as exc_info:
        resolver.resolve(manifest)

    assert str(exc_info.value) == "ERROR: invalid license for local asset hero"


def test_wave3_schema_fields_present_on_found_asset(tmp_path: Path) -> None:
    """A successfully resolved local asset carries the three schema metadata fields."""
    _write_asset(tmp_path, "characters", "hero.png")

    manifest = _make_manifest(character_packs=[{"asset_id": "hero", "license_type": "proprietary_cleared"}])
    resolver = LocalAssetResolver(assets_root=str(tmp_path))
    results = resolver.resolve(manifest)

    assert len(results) == 1
    data = json.loads(results[0].model_dump_json())

    assert data["schema_id"] == "urn:media:resolved-asset"
    assert data["schema_version"] == "1.0.0"
    assert data["producer"] == "media/resolvers/local"


def test_wave3_schema_fields_present_on_placeholder(tmp_path: Path) -> None:
    """A placeholder asset (no local file found) also carries the three schema metadata fields."""
    manifest = _make_manifest(character_packs=[{"asset_id": "ghost"}])
    resolver = LocalAssetResolver(assets_root=str(tmp_path))
    results = resolver.resolve(manifest)

    assert len(results) == 1
    data = json.loads(results[0].model_dump_json())

    assert data["schema_id"] == "urn:media:resolved-asset"
    assert data["schema_version"] == "1.0.0"
    assert data["producer"] == "media/resolvers/local"


def test_wave3_two_run_json_bytes_identical(tmp_path: Path) -> None:
    """Resolving the same manifest twice yields byte-identical JSON with the new schema fields."""
    _write_asset(tmp_path, "characters", "hero.png")

    manifest = _make_manifest(
        character_packs=[
            {"asset_id": "hero", "license_type": "proprietary_cleared"},
            {"asset_id": "ghost"},   # missing → placeholder
        ]
    )
    resolver = LocalAssetResolver(assets_root=str(tmp_path))
    first = resolver.resolve(manifest)
    second = resolver.resolve(manifest)

    assert [r.model_dump_json() for r in first] == [r.model_dump_json() for r in second]


# ---------------------------------------------------------------------------
# Wave-6 tests — MEDIA_LIBRARY_ROOT local media library layout + resolver
# ---------------------------------------------------------------------------


def _setup_library(
    root: Path,
    asset_id: str,
    filename: str,
    license_dict: dict,
    content: bytes = b"x",
) -> None:
    """Create *images/<filename>* and *licenses/<asset_id>.license.json* under *root*."""
    images_dir = root / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / filename).write_bytes(content)

    licenses_dir = root / "licenses"
    licenses_dir.mkdir(parents=True, exist_ok=True)
    (licenses_dir / f"{asset_id}.license.json").write_text(
        json.dumps(license_dict), encoding="utf-8"
    )


def test_library_root_found_with_license(tmp_path: Path) -> None:
    """Library-root asset resolves with file:// URI and license fields from license file."""
    lib = tmp_path / "lib"
    assets = tmp_path / "assets"

    license_data = {
        "spdx_id": "CC-BY-4.0",
        "attribution_required": True,
        "text": "© 2024 Example Author",
    }
    _setup_library(lib, "hero", "hero.png", license_data)

    manifest = _make_manifest(character_packs=[{"asset_id": "hero", "license_type": "CC-BY-4.0"}])
    resolver = LocalAssetResolver(assets_root=str(assets), library_root=str(lib))
    results = resolver.resolve(manifest)

    assert len(results) == 1
    resolved = results[0]

    assert resolved.is_placeholder is False
    assert resolved.uri.endswith("hero.png")
    assert resolved.license.spdx_id == "CC-BY-4.0"
    assert resolved.license.attribution_required is True
    assert resolved.license.text == "© 2024 Example Author"


def test_library_root_missing_license_raises(tmp_path: Path) -> None:
    """Library asset present but license file absent raises ValueError with exact message."""
    lib = tmp_path / "lib"
    images_dir = lib / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / "hero.png").write_bytes(b"x")
    # Intentionally omit licenses/hero.license.json

    manifest = _make_manifest(character_packs=[{"asset_id": "hero", "license_type": "CC-BY-4.0"}])
    resolver = LocalAssetResolver(assets_root=str(tmp_path / "assets"), library_root=str(lib))

    with pytest.raises(ValueError) as exc_info:
        resolver.resolve(manifest)

    assert str(exc_info.value) == "ERROR: missing license file for local asset hero"


def test_library_root_deterministic(tmp_path: Path) -> None:
    """Resolving the same manifest against library root twice yields byte-identical JSON."""
    lib = tmp_path / "lib"
    assets = tmp_path / "assets"

    license_data = {
        "spdx_id": "CC0",
        "attribution_required": False,
        "text": "",
    }
    _setup_library(lib, "hero", "hero.png", license_data)

    manifest = _make_manifest(character_packs=[{"asset_id": "hero", "license_type": "CC0"}])
    resolver = LocalAssetResolver(assets_root=str(assets), library_root=str(lib))

    first = resolver.resolve(manifest)
    second = resolver.resolve(manifest)

    assert [r.model_dump_json() for r in first] == [r.model_dump_json() for r in second]


def test_library_root_remote_schemes_still_rejected() -> None:
    """ResolvedAsset model still rejects https:// URIs even with library code path present."""
    with pytest.raises(ValidationError):
        ResolvedAsset(
            asset_id="remote-asset",
            asset_type="character",
            uri="https://cdn.example.com/x.png",
            source=AssetSource(type="local"),
        )
