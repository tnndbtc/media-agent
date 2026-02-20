"""Pydantic models for resolved asset records (Phase 0).

Spec refs:
  §25.2 Minimum Metadata Fields — license_type, attribution, purchase_record,
        provider_or_model, retrieval_date
  §19.0 Phase 0 — is_placeholder flag, rights_warning stub
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AssetSource(BaseModel):
    """Indicates whether the asset came from a local file or was generated."""

    type: Literal["local", "generated_placeholder"]


class AssetLicense(BaseModel):
    """Minimal SPDX-oriented license block for a resolved asset."""

    spdx_id: str = "NOASSERTION"
    """SPDX license identifier or 'NOASSERTION' when not determined."""

    attribution_required: bool = False
    """True when the license requires attribution in downstream outputs."""

    text: str = ""
    """Full license text; empty when not applicable or not retrieved."""


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

    source: AssetSource
    """Origin of the asset: local file from disk or generated placeholder."""

    license: AssetLicense = Field(default_factory=AssetLicense)
    """SPDX-oriented license block; defaults to NOASSERTION when not supplied."""

    schema_id: str = "urn:media:resolved-asset"
    """Stable identifier for the resolved-asset record schema."""

    schema_version: str = "1"
    """Schema version; increment when fields are added or semantics change."""

    producer: str = "media/resolvers/local"
    """Identifier of the component that produced this record."""

    @field_validator("uri")
    @classmethod
    def _reject_remote_schemes(cls, v: str) -> str:
        """Hard-reject remote HTTP/HTTPS URIs — no network fetching allowed."""
        if v.lower().startswith(("http://", "https://")):
            raise ValueError(f"ERROR: remote uri not allowed: {v}")
        return v
