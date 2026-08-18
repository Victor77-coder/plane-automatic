from __future__ import annotations

import html
import re
from html.parser import HTMLParser

PLACEHOLDER_SNIPPETS = (
    "descrever o problema ou resultado esperado",
    "descrever o que acontece atualmente",
    "descrever o comportamento esperado",
    "explicar a causa conhecida",
    "descrever a abordagem técnica aprovada",
    "item incluído",
    "item explicitamente fora da entrega",
    "informações necessárias para reprodução",
    "critério funcional 1",
    "critério funcional 2",
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "li", "h1", "h2", "h3", "tr"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def html_to_plain(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(raw)
        parser.close()
        return parser.text()
    except Exception:
        stripped = re.sub(r"<[^>]+>", " ", raw)
        return html.unescape(re.sub(r"\s+", " ", stripped)).strip()


def is_placeholder(value: str | None) -> bool:
    text = html_to_plain(value).strip().lower()
    if not text:
        return True
    if text in {":", "-", "☐"}:
        return True
    labels_only = re.sub(
        r"(nome|organização/área|canal de entrada|data da solicitação|"
        r"pessoas ou clientes afetados|processo afetado|existe contorno|"
        r"frequência|consequência|links|screenshots|vídeos|logs|documentos|"
        r"responsável pela comunicação|sla|prazo solicitado|próxima atualização|"
        r"dependências|riscos|bloqueios|plano de rollback|ambiente|responsável|"
        r"como testar|dados necessários|pr|pipeline|deploy|logs/dashboard|"
        r"homologação|validação em produção|relação)\s*:?",
        "",
        text,
        flags=re.I,
    )
    labels_only = re.sub(r"[\s:☐•\-\*]+", "", labels_only)
    if not labels_only:
        return True
    return any(snippet in text for snippet in PLACEHOLDER_SNIPPETS)


def parse_h2_sections(description_html: str | None) -> dict[str, str]:
    raw = description_html or ""
    parts = re.split(r"<h2[^>]*>", raw, flags=re.I)
    sections: dict[str, str] = {}
    for part in parts[1:]:
        title_html, sep, rest = part.partition("</h2>")
        if not sep:
            continue
        title = html_to_plain(title_html).strip().lower()
        if title:
            sections[title] = rest.strip()
    return sections


def section_html(sections: dict[str, str], *names: str) -> str | None:
    for name in names:
        content = sections.get(name.lower())
        if content and not is_placeholder(content):
            return content
    return None


def plain_to_html(text: str | None) -> str:
    raw = (text or "").strip()
    if not raw:
        return "<p></p>"
    parts: list[str] = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        escaped = html.escape(block).replace("\n", "<br>")
        parts.append(f"<p>{escaped}</p>")
    return "".join(parts) or "<p></p>"


def as_html(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw or is_placeholder(raw):
        return None
    if re.search(r"<[a-z][\s\S]*>", raw, flags=re.I):
        return raw
    return plain_to_html(raw)
