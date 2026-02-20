.PHONY: verify-integration verify-integration-strict media-verify

verify-integration:
	python scripts/verify_media_integration.py

verify-integration-strict:
	python scripts/verify_media_integration.py --strict

media-verify:
	python scripts/media.py verify
