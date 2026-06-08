import src.email_labeling.apply as ap

_SET = dict(auto_create=True, cap=50, confidence_min=0.7, dedup_cosine=0.85, new_per_run=3)


class FakeRegistry:
    def __init__(self):
        self.added = []
        self.suggested = []

    def add(self, name, source="model"):
        self.added.append((name, source))
        return True

    def add_suggestion(self, name, message_id=""):
        self.suggested.append((name, message_id))


def test_apply_creates_and_merges():
    reg = FakeRegistry()
    names = ["work"]
    tags, n = ap.apply_dynamic_labels(
        [{"name": "Job Hunt", "confidence": 0.9}], ["newsletter"], names, reg, _SET, message_id="m1")
    assert n == 1
    assert ("job-hunt", "model") in reg.added
    assert "job-hunt" in tags and "job-hunt" in names


def test_apply_suggests_when_off():
    reg = FakeRegistry()
    tags, n = ap.apply_dynamic_labels(
        [{"name": "Job Hunt", "confidence": 0.9}], [], ["work"], reg,
        {**_SET, "auto_create": False}, message_id="m1")
    assert n == 0
    assert reg.suggested == [("job-hunt", "m1")]
    assert tags == []


def test_apply_reuses_existing():
    reg = FakeRegistry()
    tags, n = ap.apply_dynamic_labels(
        [{"name": "Finance", "confidence": 0.9}], [], ["finance"], reg, _SET, message_id="m1")
    assert n == 0 and reg.added == []
    assert "finance" in tags


def test_apply_respects_remaining_run_budget():
    reg = FakeRegistry()
    _, n = ap.apply_dynamic_labels(
        [{"name": "a", "confidence": 0.9}, {"name": "b", "confidence": 0.9}], [], ["work"], reg,
        _SET, created_so_far=2, message_id="m1")  # 3 - 2 = 1 remaining
    assert n == 1


def test_apply_empty_proposed_noop():
    reg = FakeRegistry()
    tags, n = ap.apply_dynamic_labels([], ["x"], ["work"], reg, _SET)
    assert (tags, n) == (["x"], 0)
    assert reg.added == [] and reg.suggested == []
