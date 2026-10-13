"""Shared types for extractors.

Every extractor is a pure function `(Pages) -> list[Evidence]`: no I/O, no clock except where the
caller passes `current_year`. An extractor that *could* evaluate its signal always returns a row
(value True/False), so the scorer can tell "checked and absent" from "couldn't check".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from selectolax.lexbor import LexborHTMLParser

RULE_CONFIDENCE = 0.9
HTTP_CONFIDENCE = 0.95

_BLOCK_END = re.compile(
    r"(</(?:p|h[1-6]|li|div|td|th|tr|section|article|header|footer|nav|ul|ol|table|blockquote|address|dd|dt"
    r"|title|button|label|option)\s*>|<br\s*/?>)",
    re.I,
)


@dataclass
class Evidence:
    signal: str
    value: Any
    display: str
    source_url: str | None
    snippet: str | None = None
    extractor: str = "rule"
    confidence: float = RULE_CONFIDENCE
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class PageView:
    url: str
    kind: str
    html: str

    @cached_property
    def tree(self) -> LexborHTMLParser:
        return LexborHTMLParser(self.html)

    @cached_property
    def text(self) -> str:
        """Visible text, one line per block element (so a name can't straddle a heading and a paragraph)."""
        tree = LexborHTMLParser(_BLOCK_END.sub(r"\1\n", self.html))
        for sel in ("script", "style", "noscript", "svg", "template", "iframe"):
            for n in tree.css(sel):
                n.decompose()
        root = tree.body or tree.root
        if root is None:
            return ""
        lines = (" ".join(line.split()) for line in root.text(separator=" ").split("\n"))
        return "\n".join(line for line in lines if line)

    @cached_property
    def footer_text(self) -> str:
        nodes = self.tree.css("footer, [role=contentinfo], #footer, .footer, .site-footer")
        if nodes:
            return " ".join(" ".join(n.text(separator=" ").split()) for n in nodes)
        return self.text[-1500:]


@dataclass
class Pages:
    pages: list[PageView]
    final_scheme: str | None = None
    tls_ok: bool | None = None
    ttfb_ms: int | None = None
    home_bytes: int = 0
    total_bytes: int = 0

    @property
    def home(self) -> PageView | None:
        return next((p for p in self.pages if p.kind == "home"), self.pages[0] if self.pages else None)

    @property
    def home_url(self) -> str | None:
        return self.home.url if self.home else None

    def of_kind(self, *kinds: str) -> list[PageView]:
        return [p for p in self.pages if p.kind in kinds]

    @property
    def all_html(self) -> str:
        return "\n".join(p.html for p in self.pages)

    @classmethod
    def from_crawl(cls, result: Any) -> Pages:
        """Build from a `pipeline.crawl.CrawlResult` (kept untyped to avoid an import cycle)."""
        views = [PageView(p.final_url or p.url, p.kind, p.html) for p in result.pages]
        home = result.home
        return cls(
            pages=views,
            final_scheme=result.final_scheme,
            tls_ok=result.tls_ok,
            ttfb_ms=result.ttfb_ms,
            home_bytes=home.bytes if home else 0,
            total_bytes=result.total_bytes,
        )


def clean(s: str) -> str:
    return " ".join(s.split())


def snippet_at(text: str, start: int, end: int, width: int = 200) -> str:
    """A ≤200-char window of `text` centred on [start, end), on word boundaries where possible."""
    pad = max(0, (width - (end - start)) // 2)
    a, b = max(0, start - pad), min(len(text), end + pad)
    if a > 0:
        sp = text.find(" ", a)
        a = sp + 1 if 0 <= sp < start else a
    if b < len(text):
        sp = text.rfind(" ", end, b)
        b = sp if sp > end else b
    out = clean(text[a:b])
    if a > 0:
        out = "…" + out
    if b < len(text):
        out = out + "…"
    return out[:width]


def first_match(
    pattern: re.Pattern[str], pages: list[PageView], use_footer: bool = False
) -> tuple[PageView, re.Match[str]] | None:
    for p in pages:
        hay = p.footer_text if use_footer else p.text
        m = pattern.search(hay)
        if m:
            return p, m
    return None
