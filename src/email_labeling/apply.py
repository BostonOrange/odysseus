"""Glue between the reconciler (pure decision) and the registry (persistence).

Used by the urgency classifier to turn model-proposed labels into applied tags,
created registry entries, and queued suggestions. Small and injectable so it
unit-tests without a DB or a live model.
"""
from src.email_labeling.reconciler import reconcile


def apply_dynamic_labels(proposed, tags, registry_names, registry, settings, *,
                         created_so_far=0, message_id="", embed_fn=None):
    """Reconcile ``proposed`` labels, persist creates + suggestions, merge into ``tags``.

    proposed:       [{"name","confidence"}] from the model.
    tags:           list, mutated in place and returned.
    registry_names: current label names, mutated as creates happen (so later
                    emails in the same run can reuse them).
    registry:       object exposing .add(name, source) and .add_suggestion(name, message_id).
    settings:       {auto_create, cap, confidence_min, dedup_cosine, new_per_run}.
    created_so_far: new labels already created this run (enforces the per-run budget).

    Returns ``(tags, n_created)``.
    """
    if not proposed:
        return tags, 0
    res = reconcile(
        proposed, registry_names,
        auto_create=settings["auto_create"],
        cap=settings["cap"],
        confidence_min=settings["confidence_min"],
        dedup_cosine=settings["dedup_cosine"],
        new_per_run=max(0, int(settings["new_per_run"]) - int(created_so_far)),
        embed_fn=embed_fn,
    )
    n_created = 0
    for nm in res["create"]:
        registry.add(nm, source="model")
        registry_names.append(nm)
        n_created += 1
    for nm in res["suggest"]:
        registry.add_suggestion(nm, message_id)
    for nm in res["apply"] + res["create"]:
        if nm not in tags:
            tags.append(nm)
    return tags, n_created
