"""Compatibility shim for the canonical YouTube handler.

This package historically carried a second copy of the YouTube handler, which
drifted from the canonical one (missing type-guards, a broken comment-fetch
timeout). The application runtime imports ``src.youtube_handler`` on the hot
path, so re-export from there — a single source of truth means the two import
paths can never diverge again.
"""

from src.youtube_handler import *  # noqa: F401,F403
from src.youtube_handler import (  # explicit re-exports for IDE/type-checker visibility
    YOUTUBE_INSTRUCTION_PROMPT,
    init_youtube,
    is_youtube_url,
    extract_youtube_id,
    extract_transcript_async,
    format_transcript_for_context,
    fetch_youtube_comments,
    format_comments_for_context,
)

__all__ = [
    "YOUTUBE_INSTRUCTION_PROMPT",
    "init_youtube",
    "is_youtube_url",
    "extract_youtube_id",
    "extract_transcript_async",
    "format_transcript_for_context",
    "fetch_youtube_comments",
    "format_comments_for_context",
]
