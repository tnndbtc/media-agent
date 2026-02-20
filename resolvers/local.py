"""LocalAssetResolver — Phase 0 local-only deterministic resolver.

Spec refs:
  §9      Media Acquisition Flow — priority 1: local asset library
  §19.0   Phase 0 — local assets dir only; placeholder for missing; no network
  §25.2   Minimum metadata fields per resolved asset
  §31.4   /resolvers layout

Input:  AssetManifest dict matching the canonical orchestrator schema:
          schema_version, manifest_id, project_id, shotlist_ref,
          character_packs[], backgrounds[], vo_items[]
Output: list[ResolvedAsset] — order mirrors manifest arrays
          (character_packs → backgrounds → vo_items)
"""

import os
from pathlib import Path

import structlog

from app.models.asset_manifest import AssetManifest
from models.resolution import AssetMetadata, ResolvedAsset
from resolvers.placeholder import make_placeholder
from rights.license_validator import LicenseValidator

# Fixed epoch timestamp — Phase 0 must not depend on wall-clock time.
_PHASE0_DATE = "1970-01-01T00:00:00Z"

# Default local assets root (overridden by LOCAL_ASSETS_ROOT env var).
_DEFAULT_ASSETS_ROOT = "./data/local_assets"

# Map asset_type → subdirectory name under assets_root.
_TYPE_TO_SUBDIR: dict[str, str] = {
    "character": "characters",
    "background": "backgrounds",
    "prop": "props",
    "vo": "vo",
    "sfx": "sfx",
    "music": "music",
}

# Extension preference lists — first match wins (most preferred → least).
_IMAGE_EXTS: list[str] = ["png", "jpg", "webp", "gif"]
_AUDIO_EXTS: list[str] = ["wav", "mp3", "ogg"]
_VIDEO_EXTS: list[str] = ["mp4", "webm"]

_TYPE_TO_EXT_PREF: dict[str, list[str]] = {
    "character": _IMAGE_EXTS,
    "background": _IMAGE_EXTS,
    "prop": _IMAGE_EXTS,
    "vo": _AUDIO_EXTS,
    "sfx": _AUDIO_EXTS,
    "music": _AUDIO_EXTS,
}


def _normalize_id(asset_id: str) -> str:
    """Normalise an asset identifier for filesystem lookup.

    Rules: strip whitespace → lowercase → replace spaces and underscores
    with hyphens.
    """
    return asset_id.strip().lower().replace(" ", "-").replace("_", "-")


def _derive_id(entry: dict) -> str:
    """Derive a stable fallback ID when no explicit id field is present.

    Joins all string values in *entry* (in insertion order) with hyphens,
    capped at 64 characters.  Returns 'unknown' if entry contains no strings.
    """
    parts = [str(v) for v in entry.values() if isinstance(v, str)]
    return ("-".join(parts))[:64] if parts else "unknown"


class LocalAssetResolver:
    """Resolve AssetManifest entries against a local assets directory.

    Usage::

        resolver = LocalAssetResolver()
        results = resolver.resolve(asset_manifest_dict)

    Args:
        assets_root: Absolute or relative path to the local assets root
            directory.  Defaults to the ``LOCAL_ASSETS_ROOT`` env var, or
            ``./data/local_assets/`` if the env var is not set.
    """

    def __init__(self, assets_root: str | None = None) -> None:
        root = assets_root or os.environ.get("LOCAL_ASSETS_ROOT", _DEFAULT_ASSETS_ROOT)
        self.assets_root = Path(root)
        self._validator = LicenseValidator()
        self._log = structlog.get_logger("resolvers.local")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, asset_manifest: "AssetManifest | dict") -> list[ResolvedAsset]:
        """Resolve all entries in *asset_manifest* to local files or placeholders.

        Accepts either:
        - An :class:`~app.models.asset_manifest.AssetManifest` object (entries[]
          schema) — output order preserves ``entries[]`` order.
        - A plain ``dict`` conforming to the canonical orchestrator schema
          (``character_packs[]`` → ``backgrounds[]`` → ``vo_items[]`` order).

        Returns:
            A list of :class:`~models.resolution.ResolvedAsset` objects.
            Never raises; missing assets become placeholders.
        """
        # Support typed AssetManifest objects (entries[] schema) as well as raw dicts.
        if isinstance(asset_manifest, AssetManifest):
            return [
                self._resolve_one(
                    entry.asset_type.value,  # AssetType(str, Enum) → "character" etc.
                    entry.asset_id,
                    None,                    # no license_type in ManifestEntry (Phase 0)
                )
                for entry in asset_manifest.entries
            ]

        results: list[ResolvedAsset] = []

        # 1. character_packs
        for entry in asset_manifest.get("character_packs", []):
            aid = (
                entry.get("pack_id")        # orchestrator canonical field
                or entry.get("asset_id")
                or entry.get("character_id")
                or _derive_id(entry)
            )
            results.append(
                self._resolve_one("character", aid, entry.get("license_type"))
            )

        # 2. backgrounds
        for entry in asset_manifest.get("backgrounds", []):
            aid = (
                entry.get("bg_id")          # orchestrator canonical field
                or entry.get("asset_id")
                or _derive_id(entry)
            )
            results.append(
                self._resolve_one("background", aid, entry.get("license_type"))
            )

        # 3. vo_items  (item_id is required in canonical schema; text → captions only)
        for entry in asset_manifest.get("vo_items", []):
            aid = entry.get("item_id") or _derive_id(entry)
            results.append(
                self._resolve_one("vo", aid, entry.get("license_type"))
            )

        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_one(
        self,
        asset_type: str,
        asset_id: str,
        manifest_license_type: str | None,
    ) -> ResolvedAsset:
        """Resolve a single asset entry."""
        norm_id = _normalize_id(asset_id)
        subdir = _TYPE_TO_SUBDIR.get(asset_type, asset_type + "s")
        search_dir = self.assets_root / subdir

        found_path = self._find_file(search_dir, norm_id, asset_type)

        if found_path is None:
            self._log.warning(
                "local_asset_not_found",
                asset_type=asset_type,
                asset_id=norm_id,
                search_dir=str(search_dir),
            )
            resolved = make_placeholder(asset_type, norm_id)
        else:
            license_type = manifest_license_type or "proprietary_cleared"
            resolved = ResolvedAsset(
                asset_id=asset_id,
                asset_type=asset_type,
                uri=found_path.as_uri(),
                is_placeholder=False,
                metadata=AssetMetadata(
                    license_type=license_type,
                    provider_or_model="local_library",
                    retrieval_date=_PHASE0_DATE,
                ),
            )

        # Rights validation — Phase 0: warning only, no raise.
        warning = self._validator.validate(resolved.metadata.license_type)
        if warning:
            resolved.rights_warning = warning
            self._log.warning(
                "asset_license_warning",
                asset_id=asset_id,
                license_type=resolved.metadata.license_type,
                warning=warning,
            )

        return resolved

    def _find_file(
        self, search_dir: Path, norm_id: str, asset_type: str
    ) -> Path | None:
        """Search *search_dir* for a file whose normalised stem equals *norm_id*.

        Returns the best match according to the extension preference list for
        *asset_type*, with lexicographic tie-breaking.  Returns ``None`` if the
        directory does not exist or no matching file is found.
        """
        if not search_dir.is_dir():
            return None

        # Collect files whose normalised stem matches norm_id.
        candidates = [
            f
            for f in search_dir.iterdir()
            if f.is_file() and _normalize_id(f.stem) == norm_id
        ]

        if not candidates:
            return None

        pref = _TYPE_TO_EXT_PREF.get(asset_type, _IMAGE_EXTS)

        def _sort_key(p: Path) -> tuple[int, str]:
            ext = p.suffix.lstrip(".").lower()
            try:
                return (pref.index(ext), p.name)
            except ValueError:
                # Unknown extension → sorted after all preferred ones, then by name.
                return (len(pref), p.name)

        return sorted(candidates, key=_sort_key)[0]
