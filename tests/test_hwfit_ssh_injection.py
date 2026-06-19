"""Regression tests for the hwfit SSH option-injection RCE.

A `host` query param like `-oProxyCommand=<cmd>` is parsed by ssh as an
OPTION, not a hostname, so ssh runs `<cmd>` on the LOCAL machine. Because the
hwfit routes were unauthenticated GETs, this was a CSRF-to-RCE. These tests
pin the input validation that closes it (the route-layer admin/cross-site
gates are defense in depth on top).
"""

from unittest.mock import patch

import pytest

from services.hwfit import hardware
from services.hwfit.hardware import _safe_ssh_host, _safe_ssh_port, detect_system, _run


# --- host validation --------------------------------------------------------

@pytest.mark.parametrize("evil", [
    "-oProxyCommand=touch /tmp/pwned",
    "-otouch /tmp/x",
    "-Fbad",
    "-",
    "",
    "   ",
])
def test_safe_ssh_host_rejects_option_injection(evil):
    with pytest.raises(ValueError):
        _safe_ssh_host(evil)


@pytest.mark.parametrize("ok", ["server", "user@server", "10.0.0.5", "box.lan", "u@h.example.com"])
def test_safe_ssh_host_accepts_normal_hosts(ok):
    assert _safe_ssh_host(ok) == ok


def test_safe_ssh_host_strips_whitespace():
    assert _safe_ssh_host("  user@server  ") == "user@server"


# --- port validation --------------------------------------------------------

def test_safe_ssh_port_normalises_default_and_blank():
    assert _safe_ssh_port("") is None
    assert _safe_ssh_port("22") is None
    assert _safe_ssh_port(None) is None


def test_safe_ssh_port_accepts_valid():
    assert _safe_ssh_port("2222") == "2222"


@pytest.mark.parametrize("bad", ["-1", "abc", "99999", "0", "22; rm -rf /"])
def test_safe_ssh_port_rejects_invalid(bad):
    with pytest.raises(ValueError):
        _safe_ssh_port(bad)


# --- detect_system never probes a malicious host ----------------------------

def test_detect_system_rejects_injection_without_executing():
    evil = "-oProxyCommand=touch /tmp/pwned"
    with patch.object(hardware, "subprocess") as mock_subprocess:
        result = detect_system(host=evil, fresh=True)
    # No subprocess was spawned at all — rejected before any probe.
    mock_subprocess.run.assert_not_called()
    assert isinstance(result, dict) and "error" in result


# --- _run defense in depth --------------------------------------------------

def test_run_refuses_dash_leading_host(monkeypatch):
    monkeypatch.setattr(hardware, "_remote_host", "-oProxyCommand=evil")
    monkeypatch.setattr(hardware, "_remote_port", None)
    with patch.object(hardware, "subprocess") as mock_subprocess:
        out = _run("echo hi")
    assert out is None
    mock_subprocess.run.assert_not_called()


def test_run_passes_valid_host_to_ssh(monkeypatch):
    monkeypatch.setattr(hardware, "_remote_host", "user@server")
    monkeypatch.setattr(hardware, "_remote_port", "2222")
    with patch.object(hardware, "subprocess") as mock_subprocess:
        mock_subprocess.run.return_value.returncode = 0
        mock_subprocess.run.return_value.stdout = "ok"
        out = _run("echo hi")
    assert out == "ok"
    argv = mock_subprocess.run.call_args[0][0]
    # Host is present, passed as a positional arg (not an option), with -p port.
    assert "user@server" in argv
    assert argv[argv.index("-p") + 1] == "2222"
    assert not argv[-2].startswith("-")  # the host slot is never an option
