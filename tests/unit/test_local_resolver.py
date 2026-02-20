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

import json
from pathlib import Path

import pytest

from models.resolution import ResolvedAsset
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
        character_packs=[{"asset_id": "hero"}],
        backgrounds=[{"asset_id": "office"}],
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

    manifest = _make_manifest(character_packs=[{"asset_id": "hero"}])
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

    manifest = _make_manifest(character_packs=[{"asset_id": "hero"}])
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
        character_packs=[{"asset_id": "alice"}],
        backgrounds=[{"asset_id": "forest"}],
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
