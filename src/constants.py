# src/constants.py
"""Compatibility shim for the canonical constants module.

Historically this carried a second copy of the application constants, which
drifted from ``core/constants.py`` (a stale APP_VERSION served by /api/version,
plus a few missing values). The canonical module is ``core.constants``; re-export
from it so ``from src.constants import X`` keeps working and the two paths can
never diverge again (mirrors ``src/database.py`` → ``core.database``).
"""

from core.constants import *  # noqa: F401,F403
from core.constants import (  # explicit re-exports for IDE/type-checker visibility
    APP_VERSION,
    BASE_DIR,
    STATIC_DIR,
    DATA_DIR,
    SESSIONS_FILE,
    MEMORY_FILE,
    MEMORY_DOC,
    PERSONAL_DIR,
    RUNBOOK_DIR,
    UPLOAD_DIR,
    FEATURES_FILE,
    SETTINGS_FILE,
    MAX_OUTPUT_CHARS,
    MAX_READ_CHARS,
    MAX_DIFF_LINES,
    MAX_CONTEXT_MESSAGES,
    REQUEST_TIMEOUT,
    OPENAI_COMPAT_PATH,
    DEFAULT_HOST,
    LLM_HOSTS,
    OPENAI_API_KEY,
    SEARXNG_INSTANCE,
    CLEANUP_ENABLED,
    CLEANUP_INTERVAL_HOURS,
    DEFAULT_TEMPERATURE,
    DEFAULT_MAX_TOKENS,
)
