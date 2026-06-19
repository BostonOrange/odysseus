"""Smoke test for the agents route registration (agent-dispatch Phase A task 4)."""
from routes.agents_routes import setup_agents_routes


def test_router_registers_list_and_import():
    router = setup_agents_routes()
    paths = {getattr(r, "path", "") for r in router.routes}
    assert "/api/agents" in paths
    assert "/api/agents/import" in paths
