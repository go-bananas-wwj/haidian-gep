import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen

from gep.server import build_server


class ServerTests(unittest.TestCase):
    """Break caught: a packaged demo server can no longer expose the API at runtime."""

    def test_server_exposes_health_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            server = build_server("127.0.0.1", 0, Path(directory) / "tasks.sqlite3")
            worker = threading.Thread(target=server.handle_request)
            worker.start()
            with urlopen(f"http://127.0.0.1:{server.server_port}/health", timeout=2) as response:
                payload = json.loads(response.read())
            worker.join(timeout=2)
            server.server_close()

        self.assertEqual(payload, {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
