"""Local process entry point for the GEP task API and canvas."""
from pathlib import Path
from wsgiref.simple_server import make_server

from .api import make_app


def build_server(host: str, port: int, database_path: str | Path):
    return make_server(host, port, make_app(database_path))


def serve(host: str, port: int, database_path: str | Path) -> None:
    server = build_server(host, port, database_path)
    try:
        server.serve_forever()
    finally:
        server.server_close()
