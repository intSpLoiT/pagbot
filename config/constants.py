"""
╔══════════════════════════════════════════════════════════════╗
║                         PAG CORE                            ║
║                       Global Constants                       ║
╚══════════════════════════════════════════════════════════════╝

Centralized constants used throughout the PAG Core system.

Keeping global values here prevents:
    • Repeated hard-coded values
    • Inconsistent rank names
    • Configuration duplication
    • Difficult future changes
"""


# ─────────────────────────────────────────────────────────────
# APPLICATION
# ─────────────────────────────────────────────────────────────

BOT_NAME = "PAG Core"

BOT_VERSION = "0.1.0"


# ─────────────────────────────────────────────────────────────
# RANK SYSTEM
# ─────────────────────────────────────────────────────────────

RANKS = (
    "RT",
    "ST",
    "AT",
    "ET",
    "PT",
    "LT",
)


# ─────────────────────────────────────────────────────────────
# DEFAULT VALUES
# ─────────────────────────────────────────────────────────────

DEFAULT_RANK = "RT"

DEFAULT_DATABASE_PATH = (
    "data/pag.db"
)


# ─────────────────────────────────────────────────────────────
# PAG SYSTEM CHANNELS
# ─────────────────────────────────────────────────────────────

PAG_SYSTEM_CHANNELS = (
    "role-info",
    "top-10",
    "member-spotlight",
    "achievements",
    "pag-history",
    "events",
)


# ─────────────────────────────────────────────────────────────
# SYSTEM MESSAGE TYPES
# ─────────────────────────────────────────────────────────────

SYSTEM_MESSAGE_TYPES = (
    "role_info",
    "top_10",
    "member_spotlight",
    "achievements",
    "pag_history",
    "events",
)


# ─────────────────────────────────────────────────────────────
# PAG MILESTONES
# ─────────────────────────────────────────────────────────────

PAG_MILESTONES = (
    30,
    100,
    365,
)


# ─────────────────────────────────────────────────────────────
# IMAGE SYSTEM
# ─────────────────────────────────────────────────────────────

IMAGE_FORMAT = "PNG"

IMAGE_EXTENSION = ".png"

AVATAR_SIZE = 128

DEFAULT_IMAGE_WIDTH = 1200

DEFAULT_IMAGE_HEIGHT = 675