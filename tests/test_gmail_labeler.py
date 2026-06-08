import src.email_labeling.gmail_labeler as gl


class FakeConn:
    def __init__(self, typ="OK"):
        self.calls = []
        self._typ = typ

    def uid(self, *args):
        self.calls.append(args)
        return (self._typ, [b""])


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
