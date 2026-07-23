"""
╔══════════════════════════════════════════════════════════════╗
║                         PAG CORE                            ║
║                    Application Errors                       ║
╚══════════════════════════════════════════════════════════════╝

Centralized custom exceptions used throughout PAG Core.

Keeping custom errors in one place makes it easier to:
    • Handle errors consistently
    • Log errors correctly
    • Display user-friendly messages
    • Expand the system later
"""


# ─────────────────────────────────────────────────────────────
# BASE ERROR
# ─────────────────────────────────────────────────────────────


class PAGError(Exception):
    """
    Base exception for all PAG Core errors.
    """

    pass


# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────


class ConfigurationError(PAGError):
    """
    Raised when application configuration is invalid.
    """

    pass


# ─────────────────────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────────────────────


class DatabaseError(PAGError):
    """
    Raised when a database operation fails.
    """

    pass


# ─────────────────────────────────────────────────────────────
# ROBLOX API
# ─────────────────────────────────────────────────────────────


class RobloxAPIError(PAGError):
    """
    Raised when a Roblox API request fails.
    """

    pass


# ─────────────────────────────────────────────────────────────
# IMAGE GENERATION
# ─────────────────────────────────────────────────────────────


class ImageGenerationError(PAGError):
    """
    Raised when an image generation operation fails.
    """

    pass