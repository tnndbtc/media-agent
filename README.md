# media-agent

Deterministic local asset resolver for the animation production pipeline.
Given an **AssetManifest** from the orchestrator, it resolves every asset
reference (characters, backgrounds, voice-over, SFX, music) to a local file
URI — or to a stable placeholder when the file is absent — and writes an
**AssetManifest.media** output that downstream stages can consume.

Phase 0 scope: **local files only**. No network, no generative models.
Same input + same library → byte-identical output on every run.

---

## Table of Contents

- [Quick start](#quick-start)
- [CLI reference](#cli-reference)
  - [generate\_media.py](#generate_mediapy)
  - [verify\_media\_integration.py](#verify_media_integrationpy)
  - [media.py (installed entry point)](#mediapy-installed-entry-point)
  - [setup.sh (interactive menu)](#setupsh-interactive-menu)
  - [Makefile targets](#makefile-targets)
- [Environment variables](#environment-variables)
- [Asset library layout](#asset-library-layout)
- [Input / output formats](#input--output-formats)
- [Resolution logic](#resolution-logic)
- [License types](#license-types)
- [Contract governance](#contract-governance)
- [Running tests](#running-tests)
- [Project layout](#project-layout)

---

## Quick start

```bash
# Install dependencies
pip install -r requirements.txt

# Resolve a manifest
python scripts/generate_media.py \
    --input  third_party/contracts/goldens/e2e/example_episode/AssetManifest.json \
    --output /tmp/AssetManifest.media.json

# OK: 7 assets; 0 placeholders → /tmp/AssetManifest.media.json
```

---

## CLI reference

### `generate_media.py`

Resolves an `AssetManifest.json` produced by the orchestrator and writes a
fully-annotated `AssetManifest.media.json`.

```
python scripts/generate_media.py --input <path> --output <path> [--strict]
```

| Flag | Short | Required | Description |
|---|---|---|---|
| `--input` | `-i` | ✓ | Path to input `AssetManifest.json` |
| `--output` | `-o` | ✓ | Path to write resolved `AssetManifest.media.json` |
| `--strict` | | | Exit 1 if any asset resolves to a placeholder |

**Exit codes**

| Code | Meaning |
|---|---|
| `0` | Resolved successfully |
| `1` | Resolver / validation error; or a placeholder was found in `--strict` mode |
| `2` | Bad arguments or input file not found |

**Console output** (stdout):

```
OK: 7 assets; 0 placeholders → /tmp/AssetManifest.media.json
```

---

### `verify_media_integration.py`

Resolves the manifest found in `$RUN_DIR`, runs the resolver **twice**, and
asserts that both outputs are byte-identical (determinism check).  Writes
`AssetManifest.media.json` into `$RUN_DIR`.

```
RUN_DIR=/path/to/run python scripts/verify_media_integration.py [--strict]
```

| Flag | Description |
|---|---|
| `--strict` | Fail if any resolved asset is a placeholder |

**Exit codes** match `generate_media.py` (`0` / `1` / `2`).

---

### `media.py` (installed entry point)

Top-level dispatcher installed as the `media` command by `pyproject.toml`.

```
python scripts/media.py verify   # or: media verify
```

`verify` runs `verify_media_integration.py` twice and compares outputs.
Requires `RUN_DIR` to be set; exits `2` if it is not.

---

### `setup.sh` (interactive menu)

```
./setup.sh
```

| Option | Action |
|---|---|
| `1` | Run the full test suite (pytest) then the live workflow test against the e2e golden |
| `2` | Install dependencies from `requirements.txt` |
| `3` | Print `generate_media.py` usage examples |
| `0` | Exit |

---

### Makefile targets

```bash
make generate-media INPUT=/path/to/AssetManifest.json OUTPUT=/path/to/out.json
make verify-integration            # resolve + determinism check (requires RUN_DIR)
make verify-integration-strict     # same, fail on placeholders
make media-verify                  # run media.py verify (requires RUN_DIR)
make verify-contracts              # validate all contract schemas & golden fixtures
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `MEDIA_LIBRARY_ROOT` | `tests/library/` | Primary asset library — checked first. Must contain `images/`, `audio/`, and `licenses/` subdirectories. |
| `LOCAL_ASSETS_ROOT` | `tests/library/` | Fallback asset root — used when an asset is not found in the library. Subdirectory layout: `characters/`, `backgrounds/`, `props/`, `vo/`, `sfx/`, `music/`. |
| `RUN_DIR` | *(none)* | Required by `verify_media_integration.py` and `media verify`. Directory that contains `AssetManifest.json` and receives `AssetManifest.media.json`. |

---

## Asset library layout

`MEDIA_LIBRARY_ROOT` must follow this structure:

```
<library_root>/
├── images/          # character, background, prop assets
│   └── <asset-id>.<png|jpg|webp|gif>
├── audio/           # vo, sfx, music assets
│   └── <asset-id>.<wav|mp3|ogg>
└── licenses/        # one JSON file per asset
    └── <asset-id>.license.json
```

**License file format:**

```json
{
  "spdx_id": "CC0",
  "attribution_required": false,
  "text": ""
}
```

Asset IDs are normalised before lookup: lowercased, spaces and underscores
replaced with hyphens.  Extension preference when multiple files match:
`png > jpg > webp > gif` (images) and `wav > mp3 > ogg` (audio).

---

## Input / output formats

### Input — `AssetManifest.json`

Schema: `third_party/contracts/schemas/AssetManifest.v1.json`

```json
{
  "schema_id": "AssetManifest",
  "schema_version": "1.0.0",
  "manifest_id": "manifest-example",
  "project_id": "my-project",
  "shotlist_ref": "shotlist-example",
  "character_packs": [
    { "pack_id": "char-hero", "asset_id": "char-hero", "license_type": "proprietary_cleared" }
  ],
  "backgrounds": [
    { "bg_id": "bg-scene-001", "asset_id": "bg-scene-001", "license_type": "proprietary_cleared" }
  ],
  "vo_items": [
    { "item_id": "vo-scene-001-hero-000", "speaker_id": "hero",
      "text": "Hello world.", "license_type": "generated_local" }
  ]
}
```

### Output — `AssetManifest.media.json`

Schema: `third_party/contracts/schemas/AssetManifest.media.v1.json`

```json
{
  "schema_id": "AssetManifest.media",
  "schema_version": "1.0.0",
  "manifest_id": "manifest-example",
  "project_id": "my-project",
  "producer": "media/generate_media.py",
  "generated_at": "1970-01-01T00:00:00Z",
  "items": [
    {
      "asset_id": "char-hero",
      "asset_type": "character",
      "uri": "file:///abs/path/to/char-hero.png",
      "is_placeholder": false,
      "source": { "type": "local" },
      "license": { "spdx_id": "CC0", "attribution_required": false, "text": "" },
      "metadata": {
        "license_type": "CC0",
        "provider_or_model": "local_library",
        "retrieval_date": "1970-01-01T00:00:00Z"
      },
      "schema_id": "urn:media:resolved-asset",
      "schema_version": "1.0.0",
      "producer": "media/resolvers/local"
    }
  ]
}
```

Missing assets use `"uri": "placeholder://<type>/<id>"` and
`"is_placeholder": true`.

---

## Resolution logic

1. **Library pass** (`MEDIA_LIBRARY_ROOT`) — look in `images/` or `audio/`
   depending on asset type.  If found, load the matching `.license.json` and
   return a resolved asset.

2. **Fallback pass** (`LOCAL_ASSETS_ROOT`) — look in the type-specific
   subdirectory (`characters/`, `backgrounds/`, `vo/`, …).  If found and the
   manifest supplies a valid `license_type`, return a resolved asset.  If not
   found, emit a `local_asset_not_found` warning and return a placeholder.

3. **Rights check** — unknown or disallowed license types emit an
   `asset_license_warning` log entry.  In Phase 0 this never raises.

---

## License types

| Value | Meaning |
|---|---|
| `proprietary_cleared` | Cleared proprietary asset |
| `CC0` | Public domain (Creative Commons Zero) |
| `commercial_licensed` | Commercial license on file |
| `generated_local` | Locally generated (TTS, procedural, etc.) |
| `placeholder` | Auto-assigned to placeholder assets |

---

## Contract governance

Contracts live in `third_party/contracts/` and are versioned separately.
The pinned protocol version is in `PROTOCOL_VERSION`.

```
third_party/contracts/
├── schemas/          # 7 JSON Schema files (*.v1.json)
├── goldens/
│   ├── minimal/      # Minimal valid instance per schema
│   └── e2e/          # Full end-to-end golden fixtures
├── compat/
│   ├── protocol_version.json
│   └── field_allowlist.json
└── tools/
    └── verify_contracts.py
```

Validate all schemas and golden fixtures:

```bash
make verify-contracts
```

---

## Running tests

```bash
pytest              # all tests
pytest -q           # quiet (summary only)
pytest -v           # verbose
pytest tests/unit/test_local_resolver.py   # single file
```

The test suite covers unit tests for the resolver, determinism verification,
schema validation, contract golden fixture compliance, and end-to-end library
resolution.  `tests/library/` is the default fixture library used when neither
`MEDIA_LIBRARY_ROOT` nor `LOCAL_ASSETS_ROOT` is set.

---

## Project layout

```
media-agent/
├── app/models/           # Typed AssetManifest model (orchestrator schema)
├── models/               # ResolvedAsset, AssetMetadata, AssetLicense, AssetSource
├── resolvers/
│   ├── local.py          # LocalAssetResolver — main resolver
│   └── placeholder.py    # Placeholder factory
├── rights/
│   └── license_validator.py
├── scripts/
│   ├── generate_media.py           # CLI: resolve a manifest
│   ├── verify_media_integration.py # CLI: determinism check
│   └── media.py                    # Installed entry point
├── tests/
│   ├── library/          # Fixture asset library (images, audio, licenses)
│   └── unit/
├── third_party/contracts/          # Schemas, goldens, governance tools
├── pyproject.toml
├── Makefile
└── setup.sh
```
