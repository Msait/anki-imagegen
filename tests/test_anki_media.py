import base64
import socket

import pytest

from anki_imagegen.anki_media import (
    AnkiConnectError,
    AnkiMedia,
    AnkiUnreachableError,
    media_filename,
)


def test_media_filename_is_deterministic():
    assert media_filename(1712345678901) == "anki-img-1712345678901.png"


@pytest.mark.parametrize("bad", [0, -5, "123", 1.0, True, None])
def test_media_filename_rejects_bad_ids(bad):
    with pytest.raises(ValueError, match="note_id"):
        media_filename(bad)


def test_version_sends_v6_request(fake_anki):
    assert AnkiMedia(fake_anki.url).version() == 6
    assert fake_anki.requests == [{"action": "version", "version": 6, "params": {}}]


def test_store_media_sends_base64_and_overwrites(fake_anki):
    stored = AnkiMedia(fake_anki.url).store_media("anki-img-1.png", b"\x89PNG data")
    assert stored == "anki-img-1.png"
    params = fake_anki.requests[0]["params"]
    assert fake_anki.requests[0]["action"] == "storeMediaFile"
    assert params["filename"] == "anki-img-1.png"
    assert base64.b64decode(params["data"]) == b"\x89PNG data"
    assert params["deleteExisting"] is True


def test_anki_error_is_raised(fake_anki):
    fake_anki.responses["storeMediaFile"] = {"result": None, "error": "collection is not available"}
    with pytest.raises(AnkiConnectError, match="collection is not available"):
        AnkiMedia(fake_anki.url).store_media("anki-img-1.png", b"x")


def test_malformed_response_is_raised(fake_anki):
    fake_anki.responses["version"] = {"unexpected": True}
    with pytest.raises(AnkiConnectError, match="unexpected response"):
        AnkiMedia(fake_anki.url).version()


def test_truncated_response_is_anki_error(fake_anki):
    fake_anki.responses["storeMediaFile"] = "truncate"
    with pytest.raises(AnkiConnectError, match="storeMediaFile"):
        AnkiMedia(fake_anki.url).store_media("anki-img-1.png", b"x")


def test_unreachable_has_actionable_message():
    with socket.socket() as s:  # grab a free port, then close it so nothing listens
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(AnkiUnreachableError, match="Open Anki with AnkiConnect enabled"):
        AnkiMedia(f"http://127.0.0.1:{port}", timeout=1).version()


def test_ignores_http_proxy_env(fake_anki, monkeypatch):
    for var in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(var, "http://10.255.255.1:3128")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    assert AnkiMedia(fake_anki.url, timeout=2).version() == 6
