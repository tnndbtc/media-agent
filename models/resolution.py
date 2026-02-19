"""Pydantic models for resolved asset records (Phase 0).

Spec refs:
  §25.2 Minimum Metadata Fields — license_type, attribution, purchase_record,
        provider_or_model, retrieval_date
  §19.0 Phase 0 — is_placeholder flag, rights_warning stub
"""

from pydantic import BaseModel, Field


class AssetMetadata(BaseModel):
    """Minimum provenance metadata per §25.2."""

    license_type: str
    """e.g. 'proprietary_cleared', 'CC0', 'commercial_licensed', 'generated_local', 'placeholder'"""

    attribution: str = ""
    """Required for CC-BY and similar; empty for proprietary/generated assets."""

    purchase_record: str = ""
    """URI or reference to invoice/license doc; empty in Phase 0."""

    provider_or_model: str = "local_library"
    """Source tool, platform, or model name."""

    retrieval_date: str = "1970-01-01T00:00:00Z"
    """ISO 8601 acquisition date. Fixed epoch value in Phase 0 for determinism."""


class ResolvedAsset(BaseModel):
    """A single resolved asset record returned by the resolver."""

    asset_id: str
    """Original asset identifier from the manifest."""

    asset_type: str
    """Asset category: 'character', 'background', 'prop', 'vo', 'sfx', 'music'."""

    uri: str
    """
    Resolved URI.
    - Local file:  ``file:///abs/path/to/asset.png``
    - Placeholder: ``placeholder://<asset_type>/<normalized_id>``
    """

    is_placeholder: bool = False
    """True when no local file was found and a placeholder was emitted."""

    metadata: AssetMetadata = Field(default_factory=AssetMetadata)
    """Provenance metadata (§25.2 minimum fields)."""

    rights_warning: str = ""
    """
    Non-empty when license_type is not in the allowed set.
    Phase 0: warning only — no hard block.
    """
