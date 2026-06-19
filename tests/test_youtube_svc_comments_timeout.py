"""Regression: services/youtube fetch_youtube_comments must honour its timeout.

The services/youtube copy had drifted from src/youtube_handler: the timeout
wrapped ``create_subprocess_exec`` (returns as soon as the child spawns) and
then called a bare ``proc.communicate()`` that could hang forever. This mirrors
the src-copy guard so both copies stay correct.
"""
import asyncio

from services.youtube import youtube_handler


def test_svc_comment_fetch_honours_timeout(monkeypatch):
    monkeypatch.setattr(youtube_handler, "_find_ytdlp", lambda: "yt-dlp")

    killed = {"value": False}

    class HangingProc:
        returncode = None

        async def communicate(self):
            await asyncio.sleep(30)  # far longer than the test timeout
            return (b"", b"")

        def kill(self):
            killed["value"] = True

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*args, **kwargs):
        return HangingProc()

    monkeypatch.setattr(
        asyncio, "create_subprocess_exec", fake_create_subprocess_exec
    )

    result = asyncio.run(
        youtube_handler.fetch_youtube_comments("vid123", timeout=0.1)
    )

    assert result["success"] is False
    assert "timed out" in result["error"].lower()
    assert result["comments"] == []
    # The overrunning child must be killed, not left running.
    assert killed["value"] is True
