"""License type validator for the asset resolver.

Phase 0 behaviour (§25.4 stub):
  - Unknown license_type → return a non-empty warning string and log WARNING.
  - Does NOT raise an exception and does NOT hard-block.
  - Hard block is deferred to the Phase 1 quality gate.
"""

from app.utils.logging import get_logger

logger = get_logger("rights.license_validator")

# Allowed license type values (§25.2 + placeholder sentinel).
ALLOWED_LICENSE_TYPES: frozenset[str] = frozenset(
    {
        "proprietary_cleared",
        "CC0",
        "commercial_licensed",
        "generated_local",
        "placeholder",
    }
)


class LicenseValidator:
    """Validates asset license_type values against the allowed set.

    Phase 0: issues warnings only; never raises.
    """

    allowed: frozenset[str] = ALLOWED_LICENSE_TYPES

    def validate(self, license_type: str) -> str:
        """Check *license_type* against the allowed set.

        Args:
            license_type: The license string to validate.

        Returns:
            An empty string if the license is allowed, or a human-readable
            warning message if it is unknown/disallowed.  The caller is
            responsible for storing and/or logging the returned message.
        """
        if license_type in self.allowed:
            return ""

        warning = (
            f"Unknown license_type '{license_type}': not in allowed set "
            f"{sorted(self.allowed)}. "
            "Asset blocked from publish (Phase 1+). Phase 0: warning only."
        )
        logger.warning(
            "unknown_license_type",
            license_type=license_type,
            allowed=sorted(self.allowed),
        )
        return warning
