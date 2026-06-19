// agents.js — Agents tab in the Memory ("Brain") modal.
//
// Lists the user's dispatchable agents (non-default crew members imported from
// framework .md files) and imports a server-side folder of agent .md files.
// Agents are invoked from chat with `@agent-name <task>`. Mirrors skills.js.

import uiModule from './ui.js';

const API = window.location.origin;
let agents = [];
let loaded = false;

function esc(s) { return uiModule.esc(String(s ?? '')); }

export async function loadAgents() {
  try {
    const res = await fetch(`${API}/api/agents`);
    const data = await res.json();
    agents = Array.isArray(data.agents) ? data.agents : [];
  } catch (e) {
    console.error('Failed to load agents:', e);
    agents = [];
  }
  loaded = true;
  renderAgentsList();
  const countEl = document.getElementById('agents-count');
  if (countEl) countEl.textContent = String(agents.length);
}

function renderAgentsList() {
  const container = document.getElementById('agents-list');
  if (!container) return;
  if (!loaded) {
    container.innerHTML = '<div style="opacity:0.4;padding:24px 0;text-align:center;font-size:11px;">Loading…</div>';
    return;
  }
  if (!agents.length) {
    container.innerHTML = '<div style="opacity:0.4;padding:24px 0;text-align:center;font-size:12px;">No agents yet. Use Import to add a folder of agent .md files.</div>';
    return;
  }
  container.classList.add('doclib-grid');
  container.innerHTML = '';
  agents.forEach((agent) => {
    const tools = Array.isArray(agent.tools) ? agent.tools : [];
    const card = document.createElement('div');
    card.className = 'doclib-card';
    card.innerHTML = `
      <div class="doclib-card-header">
        <div style="flex:1;min-width:0;">
          <code class="skill-card-name">@${esc(agent.name)}</code>
          <div style="font-size:11px;opacity:0.55;margin-top:3px;">${esc(agent.model || 'inherits chat model')}</div>
        </div>
        <span style="font-size:11px;opacity:0.5;white-space:nowrap;">${tools.length} tool${tools.length === 1 ? '' : 's'}</span>
      </div>
      ${tools.length ? `<div style="font-size:11px;opacity:0.5;margin-top:6px;word-break:break-word;">${esc(tools.join(', '))}</div>` : ''}
    `;
    container.appendChild(card);
  });
}

function setStatus(msg) {
  const el = document.getElementById('agents-import-status');
  if (el) el.textContent = msg || '';
}

async function importAgents() {
  const path = prompt('Server-side folder of agent .md files to import (admin only):', '/tmp/agents');
  if (!path) return;
  const btn = document.getElementById('agents-import-btn');
  if (btn) { btn.disabled = true; }
  setStatus('Importing…');
  try {
    const res = await fetch(`${API}/api/agents/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    });
    const data = await res.json();
    if (!res.ok) {
      setStatus('Import failed: ' + (data.detail || res.status));
    } else {
      setStatus(`Imported ${data.created} new, ${data.updated} updated.`);
      await loadAgents();
    }
  } catch (e) {
    setStatus('Import error: ' + e);
  } finally {
    if (btn) { btn.disabled = false; }
  }
}

function wire() {
  const btn = document.getElementById('agents-import-btn');
  if (btn && !btn._wired) { btn._wired = true; btn.addEventListener('click', importAgents); }
}

document.addEventListener('DOMContentLoaded', () => { wire(); loadAgents(); });

export default { loadAgents };
