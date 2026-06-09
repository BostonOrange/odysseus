import src.email_labeling.gmail_labeler as gl


class FakeConn:
    def __init__(self, typ="OK"):
        self.calls = []
        self._typ = typ

    def uid(self, *args):
        self.calls.append(args)
        return (self._typ, [b""])

    def select(self, *args):
        self.calls.append(("SELECT",) + args)
        return ("OK", [b"1"])

    def logout(self):
        self.calls.append(("LOGOUT",))


def test_apply_issues_store_with_quoted_labels():
    c = FakeConn()
    assert gl.apply_gmail_labels(c, "123", ["Work", "Job Hunt"]) is True
    assert c.calls == [("STORE", "123", "+X-GM-LABELS", '("Work" "Job Hunt")')]


def test_apply_empty_labels_is_noop():
    c = FakeConn()
    assert gl.apply_gmail_labels(c, "123", []) is False
    assert c.calls == []


def test_apply_escapes_quotes_and_backslashes():
    c = FakeConn()
    gl.apply_gmail_labels(c, "1", ['a "b" \\ c'])
    assert c.calls[0][3] == '("a \\"b\\" \\\\ c")'


def test_apply_returns_false_on_non_ok():
    assert gl.apply_gmail_labels(FakeConn(typ="NO"), "1", ["x"]) is False


def test_apply_never_raises():
    class Boom:
        def uid(self, *a):
            raise RuntimeError("imap down")

    assert gl.apply_gmail_labels(Boom(), "1", ["x"]) is False


def test_is_gmail_host():
    assert gl.is_gmail_host("imap.gmail.com")
    assert gl.is_gmail_host("IMAP.GMAIL.COM")
    assert not gl.is_gmail_host("imap.fastmail.com")
    assert not gl.is_gmail_host("")


def test_apply_for_account_disabled_never_connects():
    calls = []
    n = gl.apply_labels_for_account(lambda: calls.append("c") or FakeConn(),
                                    [{"uid": "1", "key": "a"}], {"a": {"tags": ["work"]}},
                                    enabled=False, imap_host="imap.gmail.com")
    assert n == 0 and calls == []


def test_apply_for_account_non_gmail_never_connects():
    calls = []
    n = gl.apply_labels_for_account(lambda: calls.append("c") or FakeConn(),
                                    [{"uid": "1", "key": "a"}], {"a": {"tags": ["work"]}},
                                    enabled=True, imap_host="imap.fastmail.com")
    assert n == 0 and calls == []


def test_apply_for_account_labels_only_fresh_tagged():
    conn = FakeConn()
    items = [
        {"uid": "1", "key": "a"},                  # fresh + tags -> applied
        {"uid": "2", "key": "b", "cached": True},  # cached -> skipped
        {"uid": "3", "key": "c"},                  # fresh, no tags -> skipped
    ]
    scores = {"a": {"tags": ["work", "marketing"]}, "b": {"tags": ["x"]}, "c": {"tags": []}}
    n = gl.apply_labels_for_account(lambda: conn, items, scores,
                                    enabled=True, imap_host="imap.gmail.com")
    assert n == 1
    assert ("SELECT", "INBOX") in conn.calls
    stores = [c for c in conn.calls if c[0] == "STORE"]
    assert stores == [("STORE", "1", "+X-GM-LABELS", '("work" "marketing")')]


def test_apply_for_account_never_raises_on_connect_error():
    def boom():
        raise RuntimeError("imap down")
    n = gl.apply_labels_for_account(boom, [{"uid": "1", "key": "a"}],
                                    {"a": {"tags": ["work"]}}, enabled=True,
                                    imap_host="imap.gmail.com")
    assert n == 0
