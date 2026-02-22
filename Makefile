.PHONY: verify-integration verify-integration-strict media-verify generate-media

verify-integration:
	python scripts/verify_media_integration.py

verify-integration-strict:
	python scripts/verify_media_integration.py --strict

media-verify:
	python scripts/media.py verify

# Usage: make generate-media INPUT=/path/to/AssetManifest.json OUTPUT=/path/to/AssetManifest.media.json
generate-media:
	python scripts/generate_media.py --input $(INPUT) --output $(OUTPUT)
