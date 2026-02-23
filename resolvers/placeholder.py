"""Placeholder asset factory.

Used by LocalAssetResolver when no local file matches a manifest entry.
Spec §19.0: run must complete — placeholders ensure that.
"""

from models.resolution import AssetMetadata, AssetSource, ResolvedAsset

# Fixed epoch timestamp for Phase 0 determinism (no dependency on wall-clock time).
_PHASE0_DATE = "1970-01-01T00:00:00Z"


def make_placeholder(asset_type: str, normalized_id: str) -> ResolvedAsset:
    """Return a placeholder ResolvedAsset for a missing local file.

    Args:
        asset_type:     Asset category string (e.g. ``'character'``).
        normalized_id:  Normalised asset identifier (lowercase, hyphens).

    Returns:
        A :class:`~models.resolution.ResolvedAsset` with
        ``is_placeholder=True`` and a ``placeholder://`` URI.
    """
    uri = f"placeholder://{asset_type}/{normalized_id}"
    return ResolvedAsset(
        asset_id=normalized_id,
        asset_type=asset_type,
        uri=uri,
        is_placeholder=True,
        source=AssetSource(type="generated_placeholder"),
        metadata=AssetMetadata(
            license_type="placeholder",
            attribution="",
            purchase_record="",
            provider_or_model="placeholder_stub_v0",
            retrieval_date=_PHASE0_DATE,
        ),
    )
