.PHONY: verify-integration verify-integration-strict

verify-integration:
	python scripts/verify_media_integration.py

verify-integration-strict:
	python scripts/verify_media_integration.py --strict
