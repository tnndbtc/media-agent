"""Typed AssetManifest models for the entries[] schema (Phase 0).

These Pydantic v2 models are used by Agent E (Media Resolver) when callers
pass a structured manifest rather than a raw dict conforming to the canonical
orchestrator schema.
"""

from enum import Enum

from pydantic import BaseModel


class AssetType(str, Enum):
    CHARACTER  = "character"
    BACKGROUND = "background"
    PROP       = "prop"
    VO         = "vo"
    SFX        = "sfx"
    MUSIC      = "music"


class ManifestEntry(BaseModel):
    asset_id:     str
    asset_type:   AssetType
    requirements: dict = {}


class AssetManifest(BaseModel):
    entries: list[ManifestEntry]
