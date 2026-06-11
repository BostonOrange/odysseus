"""Agent library — import Claude-Code-style agent definitions as CrewMembers.

Phase A of the sub-agent dispatch feature. See
docs/superpowers/specs/2026-06-09-agent-import-dispatch-design.md.
"""

from .agent_importer import (
    parse_agent_md,
    map_framework_tools,
    import_agents_from_dir,
    FRAMEWORK_TOOL_MAP,
)

__all__ = [
    "parse_agent_md",
    "map_framework_tools",
    "import_agents_from_dir",
    "FRAMEWORK_TOOL_MAP",
]
