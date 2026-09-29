import io
import unittest


class FakeResponse:
    def __init__(self, body=b"ok", *, status=200, content_type="text/html; charset=utf-8", headers=None):
        self.status = status
        self.headers = {"Content-Type": content_type, **(headers or {})}
        self._body = io.BytesIO(body)
        self.closed = False

    def read(self, size=-1):
        return self._body.read(size)

    def close(self):
        self.closed = True


class QueueTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, *, timeout, headers, addresses=None):
        self.calls.append((url, timeout, dict(headers), tuple(addresses or ())))
        return self.responses.pop(0)


class SafeHttpClientTests(unittest.TestCase):
    def test_public_https_url_is_fetched(self):
        """Break caught: the safety layer could reject valid public HTTP data sources."""
        from gep.agent.http import SafeHttpClient

        transport = QueueTransport([FakeResponse(b"public")])
        client = SafeHttpClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=transport)
        document = client.fetch("https://example.com/report", accepted_types=("text/html",))
        self.assertEqual(document.body, b"public")
        self.assertEqual(document.final_url, "https://example.com/report")
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(transport.calls[0][3], ("93.184.216.34",))

    def test_localhost_private_link_local_and_metadata_are_rejected(self):
        """Break caught: an agent URL could be used to reach local or cloud metadata services."""
        from gep.agent.http import SafeHttpClient, SafeHttpError

        cases = [
            ("http://localhost/admin", ["127.0.0.1"]),
            ("http://private.example/admin", ["10.0.0.7"]),
            ("http://link.example/admin", ["169.254.1.2"]),
            ("http://169.254.169.254/latest/meta-data", ["169.254.169.254"]),
        ]
        for url, addresses in cases:
            with self.subTest(url=url):
                transport = QueueTransport([FakeResponse()])
                client = SafeHttpClient(resolver=lambda _host, _port, values=addresses: values, transport=transport)
                with self.assertRaises(SafeHttpError):
                    client.fetch(url)
                self.assertEqual(transport.calls, [])

    def test_dns_rebinding_is_rechecked_before_redirect_request(self):
        """Break caught: a hostname could resolve publicly once and privately after a redirect."""
        from gep.agent.http import SafeHttpClient, SafeHttpError

        resolutions = iter((["93.184.216.34"], ["127.0.0.1"]))
        transport = QueueTransport([
            FakeResponse(status=302, headers={"Location": "/secret"}),
            FakeResponse(b"secret"),
        ])
        client = SafeHttpClient(resolver=lambda _host, _port: next(resolutions), transport=transport)
        with self.assertRaises(SafeHttpError):
            client.fetch("https://example.com/start")
        self.assertEqual(len(transport.calls), 1)

    def test_redirect_to_private_address_is_rejected(self):
        """Break caught: a public page could redirect the reader into an internal network."""
        from gep.agent.http import SafeHttpClient, SafeHttpError

        def resolver(host, _port):
            return ["93.184.216.34"] if host == "example.com" else ["10.0.0.8"]

        transport = QueueTransport([
            FakeResponse(status=302, headers={"Location": "http://internal.example/secret"}),
            FakeResponse(b"secret"),
        ])
        client = SafeHttpClient(resolver=resolver, transport=transport)
        with self.assertRaises(SafeHttpError):
            client.fetch("https://example.com/start")
        self.assertEqual(len(transport.calls), 1)

    def test_response_larger_than_default_five_mib_is_rejected(self):
        """Break caught: a remote server could exhaust worker memory with an oversized body."""
        from gep.agent.http import SafeHttpClient, SafeHttpError

        transport = QueueTransport([FakeResponse(b"x" * (5 * 1024 * 1024 + 1))])
        client = SafeHttpClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=transport)
        with self.assertRaisesRegex(SafeHttpError, "too large"):
            client.fetch("https://example.com/large")

    def test_more_than_three_redirects_is_rejected(self):
        """Break caught: a redirect loop could consume the worker budget indefinitely."""
        from gep.agent.http import SafeHttpClient, SafeHttpError

        transport = QueueTransport([
            FakeResponse(status=302, headers={"Location": f"/r{index}"}) for index in range(1, 5)
        ])
        client = SafeHttpClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=transport)
        with self.assertRaisesRegex(SafeHttpError, "redirect"):
            client.fetch("https://example.com/start")
        self.assertEqual(len(transport.calls), 4)

    def test_unaccepted_content_type_is_rejected(self):
        """Break caught: executable or binary data could be passed to a text reader."""
        from gep.agent.http import SafeHttpClient, SafeHttpError

        transport = QueueTransport([FakeResponse(b"binary", content_type="application/octet-stream")])
        client = SafeHttpClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=transport)
        with self.assertRaisesRegex(SafeHttpError, "content type"):
            client.fetch("https://example.com/file", accepted_types=("text/html", "application/pdf"))


if __name__ == "__main__":
    unittest.main()
