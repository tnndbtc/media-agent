"""LocalAssetResolver — Phase 0 local-only deterministic resolver.

Spec refs:
  §9      Media Acquisition Flow — priority 1: local asset library
  §19.0   Phase 0 — local assets dir only; placeholder for missing; no network
  §25.2   Minimum metadata fields per resolved asset
  §31.4   /resolvers layout

Input:  AssetManifest dict matching the canonical orchestrator schema:
          schema_version, manifest_id, project_id, shotlist_ref,
          character_packs[], backgrounds[], vo_items[],
          music_items[], sfx_items[]
Output: list[ResolvedAsset] — order mirrors manifest arrays
          (character_packs → backgrounds → vo_items → music_items → sfx_items)

Root resolution (3-step priority, applied independently to both roots):
  1. Explicit constructor arg or env var (MEDIA_LIBRARY_ROOT / LOCAL_ASSETS_ROOT)
  2. CWD-derived: {CWD}/projects/{project_id}/episodes/{episode_id}/assets/
     (used when the `media` command is invoked from the pipe root above projects/)
  3. Fallback: tests/library/  (repo-internal test fixture library)

Locale support:
  When `locale` is set, VO assets are resolved from a locale-prefixed path:
    {library_root}/{locale}/audio/vo/{id}.wav
  All other asset types remain locale-free.
"""

import json
import os
from pathlib import Path

import structlog

from app.models.asset_manifest import AssetManifest
from models.resolution import AssetLicense, AssetMetadata, AssetSource, ResolvedAsset
from resolvers.placeholder import make_placeholder
from rights.license_validator import LicenseValidator

# Fixed epoch timestamp — Phase 0 must not depend on wall-clock time.
_PHASE0_DATE = "1970-01-01T00:00:00Z"

# Default media library root (overridden by MEDIA_LIBRARY_ROOT env var).
# Points at tests/library/ relative to this file so it works without any env var.
_DEFAULT_LIBRARY_ROOT = Path(__file__).resolve().parent.parent / "tests" / "library"

# Default local assets root (overridden by LOCAL_ASSETS_ROOT env var).
# Falls back to tests/library so the resolver never warns about data/local_assets.
_DEFAULT_ASSETS_ROOT = _DEFAULT_LIBRARY_ROOT

# Map asset_type → subdirectory name under assets_root (Pass 2).
_TYPE_TO_SUBDIR: dict[str, str] = {
    "character": "characters",
    "background": "backgrounds",
    "prop": "props",
    "vo": "vo",
    "sfx": "sfx",
    "music": "music",
}

# Map asset_type → subdirectory name under MEDIA_LIBRARY_ROOT (Pass 1, flat layout).
_LIBRARY_TYPE_TO_SUBDIR: dict[str, str] = {
    "character": "images",
    "background": "images",
    "prop": "images",
    "vo": "audio",
    "sfx": "audio",
    "music": "audio",
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


def _derive_cwd_root(project_id: str | None, episode_id: str | None) -> str | None:
    """Derive asset root from CWD/projects/{project_id}/episodes/{episode_id}/assets/.

    Used as Priority 2 when neither MEDIA_LIBRARY_ROOT nor LOCAL_ASSETS_ROOT
    env vars are set.  Enables the ``media`` command to be invoked from the
    pipe root (above ``projects/``) without any environment configuration.

    Returns the path string if the directory exists, None otherwise.
    """
    if not project_id or not episode_id:
        return None
    candidate = (
        Path.cwd() / "projects" / project_id / "episodes" / episode_id / "assets"
    )
    return str(candidate) if candidate.is_dir() else None


class LocalAssetResolver:
    """Resolve AssetManifest entries against a local assets directory.

    Usage::

        resolver = LocalAssetResolver()
        results = resolver.resolve(asset_manifest_dict)

    Args:
        assets_root: Absolute or relative path to the local assets root
            directory.  Defaults to the ``LOCAL_ASSETS_ROOT`` env var, then
            the CWD-derived projects path, then ``tests/library/``.
        library_root: Absolute or relative path to the media library root.
            Defaults to the ``MEDIA_LIBRARY_ROOT`` env var, then the
            CWD-derived projects path, then ``tests/library/``.
        locale: BCP-47 locale tag (e.g. ``zh-Hans``) for locale-specific
            assets.  When set, VO files are resolved from
            ``{library_root}/{locale}/audio/vo/`` rather than the flat
            ``{library_root}/audio/`` path.
        project_id: Project identifier used to derive the CWD-based default
            root (Priority 2).  Typically read from the manifest.
        episode_id: Episode identifier used to derive the CWD-based default
            root (Priority 2).  Typically read from the manifest.
    """

    def __init__(
        self,
        assets_root: str | None = None,
        library_root: str | None = None,
        locale: str | None = None,
        project_id: str | None = None,
        episode_id: str | None = None,
    ) -> None:
        # Priority 2: CWD-derived path (only computed when project/episode known).
        cwd_root = _derive_cwd_root(project_id, episode_id)

        # 3-step priority for LOCAL_ASSETS_ROOT:
        #   1. explicit arg  2. env var  3. CWD-derived  4. test fallback
        root = (
            assets_root
            or os.environ.get("LOCAL_ASSETS_ROOT")
            or cwd_root
            or str(_DEFAULT_ASSETS_ROOT)
        )
        self.assets_root = Path(root).resolve()

        # 3-step priority for MEDIA_LIBRARY_ROOT (same chain):
        lib = (
            library_root
            or os.environ.get("MEDIA_LIBRARY_ROOT")
            or cwd_root
            or str(_DEFAULT_LIBRARY_ROOT)
        )
        self.library_root: Path | None = Path(lib).resolve() if lib else None

        self.locale = locale
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
          (``character_packs[]`` → ``backgrounds[]`` → ``vo_items[]`` →
          ``music_items[]`` → ``sfx_items[]`` order).

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
                    "proprietary_cleared",   # ManifestEntry has no license_type — Wave-2 default
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

        # 4. music_items
        for entry in asset_manifest.get("music_items", []):
            aid = entry.get("item_id") or _derive_id(entry)
            results.append(
                self._resolve_one("music", aid, entry.get("license_type"))
            )

        # 5. sfx_items
        for entry in asset_manifest.get("sfx_items", []):
            aid = entry.get("item_id") or _derive_id(entry)
            results.append(
                self._resolve_one("sfx", aid, entry.get("license_type"))
            )

        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _library_search_dir(self, asset_type: str) -> Path:
        """Return the Pass 1 search directory for *asset_type*.

        For VO with ``self.locale`` set:
            ``{library_root}/{locale}/audio/vo/``
        For all other types (and VO without locale):
            ``{library_root}/{_LIBRARY_TYPE_TO_SUBDIR[asset_type]}/``
        """
        if asset_type == "vo" and self.locale:
            return self.library_root / self.locale / "audio" / "vo"
        return self.library_root / _LIBRARY_TYPE_TO_SUBDIR.get(asset_type, "images")

    def _load_license_file(self, asset_id: str, found_path: Path) -> dict:
        """Load and return the license JSON for *asset_id*.

        Search order:
          1. Co-located license — ``found_path.parent/licenses/{id}.license.json``
             (matches the per-type subfolder layout used in production assets).
          2. Flat root license — ``library_root/licenses/{id}.license.json``
             (matches the legacy flat layout used in ``tests/library/``).

        Raises:
            ValueError: If neither location contains the license file.
        """
        norm_id = _normalize_id(asset_id)

        # 1. Co-located: licenses/ subfolder next to the asset file.
        colocated = found_path.parent / "licenses" / f"{norm_id}.license.json"
        if colocated.exists():
            return json.loads(colocated.read_text(encoding="utf-8"))

        # 2. Flat: licenses/ at the library root (tests/library/ layout).
        if self.library_root:
            flat = self.library_root / "licenses" / f"{norm_id}.license.json"
            if flat.exists():
                return json.loads(flat.read_text(encoding="utf-8"))

        raise ValueError(f"ERROR: missing license file for local asset {asset_id}")

    def _resolve_one(
        self,
        asset_type: str,
        asset_id: str,
        manifest_license_type: str | None,
    ) -> ResolvedAsset:
        """Resolve a single asset entry."""
        # Pass 1 — MEDIA_LIBRARY_ROOT (library root takes priority).
        if self.library_root is not None:
            norm_id = _normalize_id(asset_id)
            lib_search_dir = self._library_search_dir(asset_type)
            lib_path = self._find_file(lib_search_dir, norm_id, asset_type)
            if lib_path is not None:
                lic = self._load_license_file(asset_id, lib_path)
                return ResolvedAsset(
                    asset_id=asset_id,
                    asset_type=asset_type,
                    uri=lib_path.as_uri(),
                    is_placeholder=False,
                    source=AssetSource(type="local"),
                    license=AssetLicense(
                        spdx_id=lic.get("spdx_id", "NOASSERTION"),
                        attribution_required=lic.get("attribution_required", False),
                        text=lic.get("text", ""),
                    ),
                    metadata=AssetMetadata(
                        license_type=lic.get("spdx_id", "NOASSERTION"),
                        provider_or_model="local_library",
                        retrieval_date=_PHASE0_DATE,
                    ),
                )

        # Pass 2 — LOCAL_ASSETS_ROOT fallback.
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
            if not manifest_license_type or manifest_license_type == "NOASSERTION":
                raise ValueError(f"ERROR: invalid license for local asset {asset_id}")
            resolved = ResolvedAsset(
                asset_id=asset_id,
                asset_type=asset_type,
                uri=found_path.as_uri(),
                is_placeholder=False,
                source=AssetSource(type="local"),
                license=AssetLicense(spdx_id=manifest_license_type),
                metadata=AssetMetadata(
                    license_type=manifest_license_type,
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
