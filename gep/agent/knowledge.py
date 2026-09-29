"""Project knowledge index backed by SQLite FTS5 with a bounded fallback."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from pypdf.errors import PyPdfError

from .store import AgentStore, AgentStoreConflictError


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _utcnow() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class KnowledgeBase:
    def __init__(
        self,
        database_path: str | Path | sqlite3.Connection,
        *,
        force_fts: bool | None = None,
        fallback_scan_limit: int = 5000,
    ):
        if fallback_scan_limit <= 0 or fallback_scan_limit > 5000:
            raise ValueError("fallback_scan_limit must be between 1 and 5000")
        self.store = AgentStore(database_path)
        self.connection = self.store.connection
        self.fallback_scan_limit = fallback_scan_limit
        self.fts_available = False
        if force_fts is not False:
            try:
                self.connection.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts "
                    "USING fts5(chunk_id UNINDEXED,document_id UNINDEXED,text,locator UNINDEXED)"
                )
                self.connection.commit()
                self.fts_available = True
            except sqlite3.OperationalError:
                if force_fts is True:
                    raise

    def close(self) -> None:
        self.store.close()

    def add_document(
        self,
        document: Mapping[str, Any],
        chunks: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        content = str(document.get("content", ""))
        if chunks is None:
            chunks = (content,)
        chunks = tuple(str(chunk).strip() for chunk in chunks if str(chunk).strip())
        if not chunks:
            raise ValueError("knowledge document requires non-empty content")
        document_id = str(document.get("document_id", "")).strip()
        if not document_id:
            raise ValueError("document_id is required")
        content_sha256 = hashlib.sha256("\n".join(chunks).encode()).hexdigest()
        existing = self.connection.execute(
            "SELECT payload_json FROM knowledge_documents WHERE document_id=?", (document_id,)
        ).fetchone()
        metadata = {key: value for key, value in dict(document).items() if key != "content"}
        metadata["document_id"] = document_id
        metadata["content_sha256"] = content_sha256
        metadata.setdefault("source_url", None)
        metadata.setdefault("region_code", None)
        metadata.setdefault("year_start", None)
        metadata.setdefault("year_end", None)
        metadata.setdefault("review_state", "unreviewed")
        if existing is not None and "created_utc" not in metadata:
            metadata["created_utc"] = json.loads(existing["payload_json"])["created_utc"]
        metadata.setdefault("created_utc", _utcnow())
        for key in ("title", "publisher", "license_or_access", "locator"):
            if not str(metadata.get(key, "")).strip():
                raise ValueError(f"{key} is required")
        encoded = _json(metadata)
        if existing is not None:
            if existing["payload_json"] != encoded:
                raise AgentStoreConflictError("knowledge document identity is immutable")
            return json.loads(existing["payload_json"])

        with self.connection:
            self.connection.execute(
                "INSERT INTO knowledge_documents "
                "(document_id,title,publisher,source_url,license_or_access,locator,content_sha256,"
                "region_code,year_start,year_end,review_state,created_utc,payload_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    metadata["document_id"], metadata["title"], metadata["publisher"],
                    metadata["source_url"], metadata["license_or_access"], metadata["locator"],
                    metadata["content_sha256"], metadata["region_code"], metadata["year_start"],
                    metadata["year_end"], metadata["review_state"], metadata["created_utc"], encoded,
                ),
            )
            for sequence, text in enumerate(chunks):
                chunk_id = f"{document_id}:{sequence:04d}:{hashlib.sha256(text.encode()).hexdigest()[:12]}"
                chunk_payload = {
                    "chunk_id": chunk_id, "document_id": document_id, "sequence": sequence,
                    "text": text, "locator": metadata["locator"],
                }
                self.connection.execute(
                    "INSERT INTO knowledge_chunks "
                    "(chunk_id,document_id,sequence,text,locator,payload_json) VALUES (?,?,?,?,?,?)",
                    (chunk_id, document_id, sequence, text, metadata["locator"], _json(chunk_payload)),
                )
                if self.fts_available:
                    self.connection.execute(
                        "INSERT INTO knowledge_chunks_fts (chunk_id,document_id,text,locator) VALUES (?,?,?,?)",
                        (chunk_id, document_id, text, metadata["locator"]),
                    )
        return metadata

    @staticmethod
    def _filters(filters: Mapping[str, Any] | None) -> tuple[list[str], list[Any]]:
        filters = filters or {}
        clauses: list[str] = []
        parameters: list[Any] = []
        if filters.get("region_code") is not None:
            clauses.append("d.region_code=?")
            parameters.append(str(filters["region_code"]))
        if filters.get("year") is not None:
            clauses.append("(d.year_start IS NULL OR d.year_start<=?) AND (d.year_end IS NULL OR d.year_end>=?)")
            parameters.extend((int(filters["year"]), int(filters["year"])))
        if filters.get("review_state") is not None:
            clauses.append("d.review_state=?")
            parameters.append(str(filters["review_state"]))
        return clauses, parameters

    @staticmethod
    def _hit(row: sqlite3.Row) -> dict[str, Any]:
        metadata = json.loads(row["payload_json"])
        return {
            **metadata,
            "fragment": row["text"][:1000],
            "locator": row["chunk_locator"] or metadata["locator"],
        }

    def search(
        self,
        query: str,
        *,
        filters: Mapping[str, Any] | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        query = query.strip()
        if not query or limit <= 0 or limit > 100:
            raise ValueError("query is required and limit must be between 1 and 100")
        clauses, parameters = self._filters(filters)
        selected = (
            "SELECT d.payload_json,c.text,c.locator AS chunk_locator "
            "FROM knowledge_chunks c JOIN knowledge_documents d ON d.document_id=c.document_id"
        )
        if self.fts_available:
            selected = (
                "SELECT d.payload_json,c.text,c.locator AS chunk_locator "
                "FROM knowledge_chunks_fts f "
                "JOIN knowledge_chunks c ON c.chunk_id=f.chunk_id "
                "JOIN knowledge_documents d ON d.document_id=c.document_id"
            )
            escaped = query.replace('"', '""')
            where = ["knowledge_chunks_fts MATCH ?", *clauses]
            values = [f'"{escaped}"', *parameters, limit]
            sql = f"{selected} WHERE {' AND '.join(where)} ORDER BY bm25(knowledge_chunks_fts),d.document_id,c.sequence LIMIT ?"
        else:
            where = ["instr(c.text, ?) > 0", *clauses]
            values = [query, *parameters, self.fallback_scan_limit]
            sql = (
                f"{selected} WHERE {' AND '.join(where)} "
                "ORDER BY d.document_id,c.sequence LIMIT ?"
            )
        rows = self.connection.execute(sql, values).fetchall()
        if self.fts_available and not rows and any("\u3400" <= character <= "\u9fff" for character in query):
            fallback_where = ["instr(c.text, ?) > 0", *clauses]
            fallback_sql = (
                "SELECT d.payload_json,c.text,c.locator AS chunk_locator "
                "FROM knowledge_chunks c JOIN knowledge_documents d ON d.document_id=c.document_id "
                f"WHERE {' AND '.join(fallback_where)} "
                "ORDER BY d.document_id,c.sequence LIMIT ?"
            )
            rows = self.connection.execute(
                fallback_sql, [query, *parameters, self.fallback_scan_limit]
            ).fetchall()
        return [self._hit(row) for row in rows[:limit]]


def _document_title(path: Path, text: str) -> str:
    if path.suffix.lower() == ".md":
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                title = line.lstrip("# ").strip()
                if title:
                    return title
    return path.stem.replace("_", " ").replace("-", " ")


def index_knowledge(
    database_path: str | Path,
    data_root: str | Path,
    *,
    pdf_paths: Sequence[str | Path] = (),
) -> dict[str, Any]:
    """Index only known documentation folders and explicitly selected PDFs."""
    root = Path(data_root).resolve()
    if not root.is_dir():
        raise ValueError("data_root must be an existing directory")
    allowed: list[Path] = []
    for directory_name in ("04_docs", "catalog"):
        directory = root / directory_name
        if directory.is_dir():
            allowed.extend(sorted(directory.glob("*.md")))
            allowed.extend(sorted(directory.glob("*.json")))
            allowed.extend(sorted(directory.glob("*.txt")))
    explicit_pdfs = [Path(path).resolve() for path in pdf_paths]
    for path in explicit_pdfs:
        if not path.is_relative_to(root):
            raise ValueError("explicit PDF must stay inside data_root")
        allowed.append(path)

    knowledge = KnowledgeBase(database_path)
    indexed_count = 0
    unchanged_count = 0
    errors: list[dict[str, str]] = []
    try:
        for path in allowed:
            try:
                if path.is_symlink() or not path.is_file():
                    raise ValueError("source must be a regular non-symlink file")
                raw = path.read_bytes()
                if len(raw) > 20 * 1024 * 1024:
                    raise ValueError("source file exceeds the 20 MiB indexing limit")
                relative = path.relative_to(root).as_posix()
                suffix = path.suffix.lower()
                if suffix in {".md", ".json", ".txt"}:
                    text = raw.decode("utf-8")
                    if suffix == ".json":
                        payload = json.loads(text)
                        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
                    chunks = (text,)
                    title = _document_title(path, text)
                    publisher = "海淀区 GEP 项目"
                    locator = f"项目文件 {relative}"
                elif suffix == ".pdf":
                    from io import BytesIO
                    from pypdf import PdfReader as PyPdfReader

                    pdf = PyPdfReader(BytesIO(raw))
                    chunks = tuple((page.extract_text() or "").strip() for page in pdf.pages)
                    chunks = tuple(chunk for chunk in chunks if chunk)
                    if not chunks:
                        raise ValueError("PDF has no extractable text")
                    metadata = pdf.metadata or {}
                    title = str(metadata.get("/Title") or path.stem)
                    publisher = str(metadata.get("/Author") or "发布者待核验")
                    locator = f"PDF {relative}，共 {len(pdf.pages)} 页"
                else:
                    continue
                content_hash = hashlib.sha256("\n".join(chunks).encode()).hexdigest()
                identity = hashlib.sha256(f"{relative}:{content_hash}".encode()).hexdigest()[:24]
                document_id = f"knowledge-{identity}"
                existed = knowledge.connection.execute(
                    "SELECT 1 FROM knowledge_documents WHERE document_id=?", (document_id,)
                ).fetchone() is not None
                knowledge.add_document({
                    "document_id": document_id,
                    "title": title,
                    "publisher": publisher,
                    "source_url": None,
                    "license_or_access": "project-internal-review",
                    "locator": locator,
                    "region_code": "110108",
                    "year_start": None,
                    "year_end": None,
                    "review_state": "unreviewed",
                    "content": "\n".join(chunks),
                    "source_path": relative,
                }, chunks=chunks)
                if existed:
                    unchanged_count += 1
                else:
                    indexed_count += 1
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, EOFError, PyPdfError) as error:
                errors.append({"path": str(path), "error": type(error).__name__})
    finally:
        knowledge.close()
    return {
        "indexed_count": indexed_count,
        "unchanged_count": unchanged_count,
        "error_count": len(errors),
        "errors": errors,
    }
