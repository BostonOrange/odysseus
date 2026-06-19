"""Drift guards: consolidated module pairs must share one source of truth.

`constants` and `youtube` were diverged copies that silently drifted (a stale
APP_VERSION served by /api/version, a broken comment-fetch timeout, missing
type-guards). They are now canonical + re-export shim. Asserting the two import
paths resolve to the SAME object makes future drift impossible by construction —
replace a shim with a second copy and these tests fail.
"""
import importlib

import core.constants as core_constants
import src.constants as src_constants
import src.youtube_handler as src_yt
import services.youtube.youtube_handler as svc_yt


_CONSTANT_NAMES = [
    "APP_VERSION", "BASE_DIR", "STATIC_DIR", "DATA_DIR",
    "SESSIONS_FILE", "MEMORY_FILE", "MEMORY_DOC", "PERSONAL_DIR",
    "RUNBOOK_DIR", "UPLOAD_DIR", "FEATURES_FILE", "SETTINGS_FILE",
    "MAX_OUTPUT_CHARS", "MAX_READ_CHARS", "MAX_DIFF_LINES",
    "MAX_CONTEXT_MESSAGES", "REQUEST_TIMEOUT", "OPENAI_COMPAT_PATH",
    "DEFAULT_HOST", "LLM_HOSTS", "OPENAI_API_KEY", "SEARXNG_INSTANCE",
    "CLEANUP_ENABLED", "CLEANUP_INTERVAL_HOURS",
    "DEFAULT_TEMPERATURE", "DEFAULT_MAX_TOKENS",
]

_YOUTUBE_PUBLIC = [
    "init_youtube", "is_youtube_url", "extract_youtube_id",
    "extract_transcript_async", "format_transcript_for_context",
    "fetch_youtube_comments", "format_comments_for_context",
]


def test_src_constants_is_a_shim_of_core():
    # core.constants re-exports from src.constants (`from src.constants import *`).
    # A prior test that reloads src.constants to probe env handling (e.g.
    # test_fastembed_cache_path) mints fresh canonical objects, leaving core bound
    # to stale ones. Re-run the shim's import against the CURRENT src.constants so
    # this drift guard is order-independent — reloading only the shim, never
    # src.constants itself, so no other test's references are invalidated.
    importlib.reload(core_constants)
    for name in _CONSTANT_NAMES:
        assert hasattr(core_constants, name), f"core.constants missing {name}"
        assert hasattr(src_constants, name), f"src.constants missing {name}"
        assert getattr(src_constants, name) is getattr(core_constants, name), (
            f"src.constants.{name} is not the same object as core.constants.{name} "
            "— the shim drifted into a separate copy"
        )


def test_services_youtube_is_a_shim_of_src():
    for name in _YOUTUBE_PUBLIC:
        assert getattr(svc_yt, name) is getattr(src_yt, name), (
            f"services.youtube.youtube_handler.{name} is not src.youtube_handler.{name} "
            "— the shim drifted into a separate copy"
        )
