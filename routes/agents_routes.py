"""Agent library routes — import framework agents, list the owner's agents.

Agents are non-default CrewMember rows. `POST /api/agents/import` ingests every
`*.md` agent in a server-side folder (admin-only — it reads the filesystem);
`GET /api/agents` lists the caller's dispatchable agents for the UI / @-trigger.
"""
import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.database import SessionLocal, CrewMember
from core.middleware import require_admin
from src.auth_helpers import get_current_user
from services.agents.agent_importer import import_agents_from_dir


class AgentImportRequest(BaseModel):
    path: str


def setup_agents_routes() -> APIRouter:
    router = APIRouter(prefix="/api/agents", tags=["agents"])

    def _owner(request: Request) -> str:
        owner = get_current_user(request)
        if not owner:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return owner

    @router.get("")
    def list_agents(request: Request):
        """List the owner's dispatchable agents (non-default crew members)."""
        owner = _owner(request)
        db = SessionLocal()
        try:
            rows = (
                db.query(CrewMember)
                .filter(
                    CrewMember.owner == owner,
                    CrewMember.is_default_assistant == False,  # noqa: E712
                )
                .order_by(CrewMember.name.asc())
                .all()
            )
            agents = []
            for c in rows:
                try:
                    tools = json.loads(c.enabled_tools) if c.enabled_tools else []
                except (TypeError, ValueError):
                    tools = []
                agents.append({"name": c.name, "model": c.model, "tools": tools})
            return {"agents": agents}
        finally:
            db.close()

    @router.post("/import")
    def import_agents(request: Request, body: AgentImportRequest):
        """Import every `*.md` agent in a server-side folder as CrewMembers.

        Admin-only: reads a path on the server filesystem. Idempotent — re-import
        upserts by (owner, name).
        """
        require_admin(request)
        owner = _owner(request)
        try:
            results = import_agents_from_dir((body.path or "").strip(), owner=owner)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        created = sum(1 for r in results if r.get("action") == "created")
        updated = sum(1 for r in results if r.get("action") == "updated")
        return {"results": results, "created": created, "updated": updated}

    return router
