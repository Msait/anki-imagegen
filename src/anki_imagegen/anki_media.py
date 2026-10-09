"""Minimal AnkiConnect client: reachability check, media upload and note type design."""

from __future__ import annotations

import base64
import http.client
import json
import urllib.error
import urllib.request
from typing import Any

DEFAULT_URL = "http://127.0.0.1:8765"
API_VERSION = 6


class AnkiConnectError(RuntimeError):
    """AnkiConnect returned an error or an unexpected response."""


class AnkiUnreachableError(AnkiConnectError):
    """Nothing answers at the AnkiConnect URL."""


def media_filename(note_id: int) -> str:
    if type(note_id) is not int or note_id <= 0:
        raise ValueError(f"note_id must be a positive integer, got {note_id!r}")
    return f"anki-img-{note_id}.png"


class AnkiMedia:
    def __init__(self, url: str = DEFAULT_URL, timeout: float = 10.0) -> None:
        self.url = url
        self.timeout = timeout
        # Empty ProxyHandler: never route localhost traffic through HTTP(S)_PROXY.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def version(self) -> int:
        return self._invoke("version")

    def store_media(self, filename: str, data: bytes) -> str:
        return self._invoke(
            "storeMediaFile",
            filename=filename,
            data=base64.b64encode(data).decode("ascii"),
            deleteExisting=True,
        )

    def model_names(self) -> list[str]:
        return self._invoke("modelNames")

    def model_field_names(self, model: str) -> list[str]:
        return self._invoke("modelFieldNames", modelName=model)

    def model_templates(self, model: str) -> dict[str, dict[str, str]]:
        """Card types of a note type, in order: {name: {"Front": ..., "Back": ...}}."""
        return self._invoke("modelTemplates", modelName=model)

    def model_styling(self, model: str) -> str:
        return self._invoke("modelStyling", modelName=model)["css"]

    def update_model_templates(self, model: str, templates: dict[str, dict[str, str]]) -> None:
        self._invoke("updateModelTemplates", model={"name": model, "templates": templates})

    def update_model_styling(self, model: str, css: str) -> None:
        self._invoke("updateModelStyling", model={"name": model, "css": css})

    def _invoke(self, action: str, **params: Any) -> Any:
        payload = json.dumps({"action": action, "version": API_VERSION, "params": params}).encode()
        request = urllib.request.Request(
            self.url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                body = json.loads(response.read())
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            raise AnkiUnreachableError(
                f"AnkiConnect is not reachable at {self.url}: {e}. "
                "Open Anki with AnkiConnect enabled."
            ) from e
        except http.client.HTTPException as e:  # e.g. connection dropped mid-response
            raise AnkiConnectError(f"AnkiConnect {action}: broken response: {e!r}") from e
        if not isinstance(body, dict) or set(body) != {"result", "error"}:
            raise AnkiConnectError(f"AnkiConnect {action}: unexpected response {body!r}")
        if body["error"] is not None:
            raise AnkiConnectError(f"AnkiConnect {action} failed: {body['error']}")
        return body["result"]
