import src.email_labeling.reconciler as rc

_SET = dict(auto_create=True, cap=50, confidence_min=0.7, dedup_cosine=0.85, new_per_run=3)


def test_normalize():
    assert rc.normalize_label_name("Job Hunt!") == "job-hunt"
    assert rc.normalize_label_name("  Finance  ") == "finance"
    assert rc.normalize_label_name("a/b c") == "a-b-c"


def test_exact_match_reuses_existing():
    out = rc.reconcile([{"name": "Finance", "confidence": 0.9}], ["finance", "work"], **_SET)
    assert out == {"apply": ["finance"], "create": [], "suggest": []}


def test_new_label_created_when_allowed():
    out = rc.reconcile([{"name": "Job Hunt", "confidence": 0.9}], ["work"], **_SET)
    assert out == {"apply": [], "create": ["job-hunt"], "suggest": []}


def test_new_label_suggested_when_auto_create_off():
    out = rc.reconcile([{"name": "Job Hunt", "confidence": 0.9}], ["work"], **{**_SET, "auto_create": False})
    assert out["suggest"] == ["job-hunt"] and out["create"] == []


def test_low_confidence_suggested_not_created():
    out = rc.reconcile([{"name": "Job Hunt", "confidence": 0.3}], ["work"], **_SET)
    assert out["suggest"] == ["job-hunt"] and out["create"] == []


def test_cap_blocks_creation():
    out = rc.reconcile([{"name": "newone", "confidence": 0.9}], ["work"], **{**_SET, "cap": 1})
    assert out["create"] == [] and out["suggest"] == ["newone"]


def test_per_run_budget_limits_creates():
    out = rc.reconcile(
        [{"name": "a", "confidence": 0.9}, {"name": "b", "confidence": 0.9}],
        ["work"], **{**_SET, "new_per_run": 1})
    assert out["create"] == ["a"] and out["suggest"] == ["b"]


def test_embedding_dedup_reuses_near_duplicate():
    vecs = {"job-search": [1.0, 0.0], "job-hunt": [0.99, 0.14]}  # cosine ~0.99 >= 0.85

    def embed_fn(names):
        return [vecs[n] for n in names]

    out = rc.reconcile([{"name": "Job Hunt", "confidence": 0.9}], ["job-search"],
                       embed_fn=embed_fn, **_SET)
    assert out["apply"] == ["job-search"] and out["create"] == []


def test_embedding_below_threshold_creates():
    vecs = {"work": [1.0, 0.0], "cooking": [0.0, 1.0]}  # cosine 0 < 0.85

    def embed_fn(names):
        return [vecs[n] for n in names]

    out = rc.reconcile([{"name": "Cooking", "confidence": 0.9}], ["work"],
                       embed_fn=embed_fn, **_SET)
    assert out["create"] == ["cooking"]


def test_duplicate_proposals_collapse():
    out = rc.reconcile(
        [{"name": "Job Hunt", "confidence": 0.9}, {"name": "job-hunt", "confidence": 0.9}],
        ["work"], **_SET)
    assert out["create"] == ["job-hunt"]
