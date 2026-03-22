"""Extract URLs from email text and HTML bodies."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser


@dataclass
class RawLink:
    url: str
    display_text: str = ""
    source: str = ""  # "text" or "html"


class _AnchorParser(HTMLParser):
    """Extract href and anchor text from HTML."""

    def __init__(self):
        super().__init__()
        self.links: list[RawLink] = []
        self._in_a = False
        self._href = ""
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag.lower() == "a":
            self._in_a = True
            self._text_parts = []
            for name, value in attrs:
                if name.lower() == "href" and value:
                    self._href = value

    def handle_data(self, data: str):
        if self._in_a:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str):
        if tag.lower() == "a" and self._in_a:
            self._in_a = False
            if self._href:
                self.links.append(
                    RawLink(
                        url=self._href,
                        display_text="".join(self._text_parts).strip(),
                        source="html",
                    )
                )
            self._href = ""
            self._text_parts = []


# Match http/https URLs in plain text
_URL_RE = re.compile(
    r'https?://[^\s<>"\'\)]+',
    re.IGNORECASE,
)


def extract_links_from_text(text: str) -> list[RawLink]:
    """Extract URLs from plain text."""
    if not text:
        return []
    return [RawLink(url=m.group(0), source="text") for m in _URL_RE.finditer(text)]


def extract_links_from_html(html: str) -> list[RawLink]:
    """Extract anchor href + display text from HTML."""
    if not html:
        return []
    parser = _AnchorParser()
    try:
        parser.feed(html)
    except Exception:
        pass
    # Also find URLs in raw HTML not in anchors
    text_urls = _URL_RE.findall(html)
    href_set = {link.url for link in parser.links}
    for url in text_urls:
        if url not in href_set:
            parser.links.append(RawLink(url=url, source="html"))
    return parser.links


def extract_all_links(body_text: str, body_html: str) -> list[RawLink]:
    """Combine links from text and HTML bodies."""
    links = extract_links_from_text(body_text)
    links.extend(extract_links_from_html(body_html))
    return links
