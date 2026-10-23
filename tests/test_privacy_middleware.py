from __future__ import annotations

import asyncio
import io
import logging
import os
import unittest

from app.privacy_middleware import PrivacyAndAuthMiddleware


class PrivacyMiddlewareTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["API_TOKEN"] = "unit-test-token"

    def run_request(self, *, token: str, path: str = "/v1/chat/completions") -> tuple[list[dict], str]:
        sent: list[dict] = []
        receive_called = False

        async def app(scope, receive, send):
            nonlocal receive_called
            receive_called = True
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"secret generated answer"})

        async def receive():
            raise AssertionError("middleware must not read the prompt body")

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [
                (b"authorization", f"Bearer {token}".encode()),
                (b"x-request-id", b"request-1"),
            ],
        }
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger = logging.getLogger("privacy_access")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        try:
            asyncio.run(PrivacyAndAuthMiddleware(app)(scope, receive, send))
        finally:
            logger.removeHandler(handler)
        if token == "unit-test-token" and path != "/health":
            self.assertTrue(receive_called)
        return sent, stream.getvalue()

    def test_authorized_request_logs_metadata_only(self) -> None:
        sent, log = self.run_request(token="unit-test-token")
        self.assertEqual(sent[0]["status"], 200)
        self.assertIn("inference_http_request", log)
        self.assertNotIn("secret generated answer", log)
        self.assertNotIn("unit-test-token", log)

    def test_unauthorized_request_is_rejected_before_app(self) -> None:
        sent, log = self.run_request(token="wrong")
        self.assertEqual(sent[0]["status"], 401)
        self.assertIn('"status":401', log)

    def test_health_is_public(self) -> None:
        sent, _ = self.run_request(token="", path="/health")
        self.assertEqual(sent[0]["status"], 200)


if __name__ == "__main__":
    unittest.main()

