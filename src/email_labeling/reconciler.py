"""Decide, per model-proposed label, whether to reuse an existing label,
create a new one, or queue it as a suggestion.

Pure/deterministic given its inputs. Embedding similarity is *injected* via
``embed_fn`` so this module stays unit-testable without numpy or a live
embedder. Cosine is computed in pure Python (works on lists or numpy rows).
"""
import re
from typing import Callable, Optional, Sequence

_NONWORD_RE = re.compile(r"[^a-z0-9]+")


def normalize_label_name(name: str) -> str:
    """Lowercase, trim, collapse runs of non-alphanumerics to single hyphens.

    'Job Hunt!' -> 'job-hunt';  '  Finance  ' -> 'finance';  'a/b c' -> 'a-b-c'.
    """
    s = (name or "").strip().lower()
    s = _NONWORD_RE.sub("-", s).strip("-")
    return s


def _cosine(a, b) -> float:
    """Cosine similarity of two vectors (sequences of floats). -1.0 on bad input."""
    if a is None or b is None:
        return -1.0
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    na = sum(float(x) * float(x) for x in a) ** 0.5
    nb = sum(float(y) * float(y) for y in b) ** 0.5
    if na == 0 or nb == 0:
        return -1.0
    return dot / (na * nb)


def reconcile(
    proposed: Sequence[dict],
    existing: Sequence[str],
    *,
    auto_create: bool,
    cap: int,
    confidence_min: float,
    dedup_cosine: float,
    new_per_run: int,
    embed_fn: Optional[Callable[[list], list]] = None,
) -> dict:
    """Resolve proposed labels against the existing registry.

    proposed: list of {"name": str, "confidence": float}.
    existing: current registry label names (any case; normalized here).
    embed_fn: optional names->vectors callable for near-duplicate dedup.

    Returns {"apply": [...existing names...], "create": [...new norm names...],
    "suggest": [...new norm names...]}. A proposal is *applied* (reuse) on exact
    or near-duplicate match, *created* when auto_create is on and all guardrails
    pass, else *suggested*.
    """
    existing_norm = {}
    for e in existing:
        existing_norm[normalize_label_name(e)] = e
    existing_keys = list(existing_norm.keys())

    emb = {}
    if embed_fn and existing_keys:
        proposed_keys = [normalize_label_name(p.get("name", "")) for p in proposed]
        to_embed = existing_keys + [k for k in proposed_keys if k and k not in existing_norm]
        if to_embed:
            for name, vec in zip(to_embed, embed_fn(to_embed)):
                emb[name] = vec

    apply_, create_, suggest_ = [], [], []
    seen = set()
    created_this_run = 0
    cap_room = cap - len(existing_keys)

    for p in proposed:
        key = normalize_label_name(p.get("name", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        conf = float(p.get("confidence", 0.0) or 0.0)

        # 1. exact normalized match -> reuse existing
        if key in existing_norm:
            apply_.append(existing_norm[key])
            continue

        # 2. near-duplicate (embedding) -> reuse closest existing above threshold
        if embed_fn and key in emb and existing_keys:
            best_k, best_sim = None, -1.0
            for ek in existing_keys:
                sim = _cosine(emb.get(key), emb.get(ek))
                if sim > best_sim:
                    best_k, best_sim = ek, sim
            if best_k is not None and best_sim >= dedup_cosine:
                apply_.append(existing_norm[best_k])
                continue

        # 3. genuinely new
        if (auto_create and conf >= confidence_min and cap_room > 0
                and created_this_run < new_per_run):
            create_.append(key)
            created_this_run += 1
            cap_room -= 1
            existing_norm[key] = key          # subsequent dups this batch reuse it
            existing_keys.append(key)
        else:
            suggest_.append(key)

    return {"apply": apply_, "create": create_, "suggest": suggest_}
