import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class FakeAnki:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.responses: dict[str, dict] = {
            "version": {"result": 6, "error": None},
            "storeMediaFile": {"result": None, "error": None},  # None = echo filename
        }
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append(body)
                if fake.responses[body["action"]] == "truncate":  # Anki dies mid-response
                    self.send_response(200)
                    self.send_header("Content-Length", "100")
                    self.end_headers()
                    self.wfile.write(b'{"res')
                    return
                response = dict(fake.responses[body["action"]])
                if body["action"] == "storeMediaFile" and response.get("result") is None and response.get("error") is None:
                    response["result"] = body["params"]["filename"]
                payload = json.dumps(response).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def fake_anki():
    fake = FakeAnki()
    yield fake
    fake.close()
