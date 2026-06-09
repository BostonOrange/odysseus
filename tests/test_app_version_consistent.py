"""Guard against the core/src constants.py copies drifting on APP_VERSION.

`core/constants.py` is a near-duplicate of `src/constants.py`. /api/version
serves the `core` copy, so a drift between them serves a stale version (it
did: core was left at 0.9.1 while src moved to 1.0.0 in the v1.0 release).
"""

from core.constants import APP_VERSION as CORE_VERSION
from src.constants import APP_VERSION as SRC_VERSION


def test_app_version_is_consistent_across_constants_copies():
    assert CORE_VERSION == SRC_VERSION, (
        f"core/constants APP_VERSION ({CORE_VERSION!r}) != "
        f"src/constants APP_VERSION ({SRC_VERSION!r}); /api/version serves the core copy"
    )


def test_app_version_is_v1():
    assert CORE_VERSION == "1.0.0"
