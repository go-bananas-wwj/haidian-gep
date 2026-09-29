"""Safe HTML and PDF text extraction for evidence collection."""
from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from typing import Any, Callable, Sequence

from .http import SafeHttpClient


@dataclass(frozen=True)
class ReadResult:
    title: str
    publisher: str
    final_url: str
    content_type: str
    text: str
    locator: str
    sha256: str
    fetched_utc: str

    def to_evidence(
        self,
        source_id: str,
        *,
        source_type: str = "web_page",
        license_or_access: str = "public_web_access_unverified",
    ) -> dict[str, Any]:
        return {
            "source_id": source_id,
            "source_type": source_type,
            "url": self.final_url,
            "final_url": self.final_url,
            "title": self.title,
            "publisher": self.publisher,
            "locator": self.locator,
            "source_sha256": self.sha256,
            "license_or_access": license_or_access,
            "tool_run_id": f"read:{self.sha256[:16]}",
            "extracted_fragment": self.text[:2000],
            "checked_utc": self.fetched_utc,
            "content_type": self.content_type,
        }


class _ArticleParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "nav", "header", "footer", "form", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.publisher = ""
        self.main_parts: list[str] = []
        self.body_parts: list[str] = []
        self._skip_depth = 0
        self._main_depth = 0
        self._title_depth = 0

    def handle_starttag(self, tag, attributes):
        tag = tag.lower()
        attrs = {str(key).lower(): value for key, value in attributes}
        if tag in self.SKIP:
            self._skip_depth += 1
        if tag in {"main", "article"}:
            self._main_depth += 1
        if tag == "title":
            self._title_depth += 1
        if tag == "meta":
            name = str(attrs.get("name") or attrs.get("property") or "").lower()
            if name in {"author", "publisher", "og:site_name"} and attrs.get("content") and not self.publisher:
                self.publisher = str(attrs["content"]).strip()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        if tag in {"main", "article"} and self._main_depth:
            self._main_depth -= 1
        if tag == "title" and self._title_depth:
            self._title_depth -= 1

    def handle_data(self, data):
        value = " ".join(data.split())
        if not value:
            return
        if self._title_depth:
            self.title_parts.append(value)
            return
        if self._skip_depth:
            return
        self.body_parts.append(value)
        if self._main_depth:
            self.main_parts.append(value)

    @property
    def text(self) -> str:
        parts = self.main_parts or self.body_parts
        return "\n".join(parts)


class WebReader:
    def __init__(self, client: SafeHttpClient):
        self.client = client

    def read(self, url: str) -> ReadResult:
        document = self.client.fetch(url, accepted_types=("text/html", "text/plain"))
        text = document.body.decode("utf-8", errors="replace")
        if document.content_type == "text/plain":
            extracted, title, publisher = text.strip(), document.final_url.rsplit("/", 1)[-1], ""
        else:
            parser = _ArticleParser()
            parser.feed(text)
            parser.close()
            extracted = parser.text.strip()
            title = " ".join(parser.title_parts).strip() or document.final_url
            publisher = parser.publisher
        if not extracted:
            raise ValueError("web page has no readable text")
        return ReadResult(
            title=title,
            publisher=publisher,
            final_url=document.final_url,
            content_type=document.content_type,
            text=extracted,
            locator="HTML 正文" if document.content_type == "text/html" else "纯文本正文",
            sha256=document.sha256,
            fetched_utc=document.fetched_utc,
        )


class PdfReader:
    def __init__(self, client: SafeHttpClient, *, pdf_factory: Callable[[BytesIO], Any] | None = None):
        self.client = client
        self.pdf_factory = pdf_factory

    def _factory(self, stream: BytesIO):
        if self.pdf_factory is not None:
            return self.pdf_factory(stream)
        from pypdf import PdfReader as PyPdfReader

        return PyPdfReader(stream)

    def read(self, url: str, pages: Sequence[int] | None = None) -> ReadResult:
        document = self.client.fetch(url, accepted_types=("application/pdf",), max_bytes=20 * 1024 * 1024)
        pdf = self._factory(BytesIO(document.body))
        selected = tuple(pages) if pages is not None else tuple(range(1, len(pdf.pages) + 1))
        if not selected or any(page < 1 or page > len(pdf.pages) for page in selected):
            raise ValueError("PDF page numbers are one-based and must exist")
        texts = [(pdf.pages[page - 1].extract_text() or "").strip() for page in selected]
        text = "\n\n".join(value for value in texts if value)
        if not text:
            raise ValueError("PDF pages have no extractable text")
        metadata = getattr(pdf, "metadata", None) or {}
        title = str(metadata.get("/Title") or url.rsplit("/", 1)[-1])
        publisher = str(metadata.get("/Author") or "")
        locator = "PDF 第 " + "、".join(str(page) for page in selected) + " 页"
        return ReadResult(
            title=title,
            publisher=publisher,
            final_url=document.final_url,
            content_type=document.content_type,
            text=text,
            locator=locator,
            sha256=document.sha256,
            fetched_utc=document.fetched_utc,
        )
