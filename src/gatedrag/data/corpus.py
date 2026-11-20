"""Document ingestion: structure-aware chunking with per-document access groups.

A document may declare its access groups on its first line:  `acl: finance, legal`.
Documents without that line are readable by the group `public`.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

_ACL_RE = re.compile(r"^\s*acl\s*:\s*(.+)$", re.I)
_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
_TEMPLATE_TAG_RE = re.compile(r"\{%.*?%\}", re.S)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    text: str
    acl: tuple[str, ...] = field(default=("public",))

    def readable_by(self, groups: set[str]) -> bool:
        return "public" in self.acl or bool(set(self.acl) & groups)


def _split_sections(body: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    title = ""
    buf: list[str] = []
    for line in body.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            if "".join(buf).strip():
                sections.append((title, "\n".join(buf).strip()))
            title, buf = m.group(1).strip(), []
        else:
            buf.append(line)
    if "".join(buf).strip():
        sections.append((title, "\n".join(buf).strip()))
    return sections


def chunk_text(text: str, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    """Pack paragraphs into chunks of at most ~max_chars, carrying `overlap` chars of context."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if cur and len(cur) + len(p) + 2 > max_chars:
            chunks.append(cur)
            cur = cur[-overlap:] + "\n\n" + p if overlap else p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
        while len(cur) > max_chars * 1.5:          # a single very long paragraph
            chunks.append(cur[:max_chars])
            cur = cur[max_chars - overlap:]
    if cur:
        chunks.append(cur)
    return chunks


def load_corpus(folder: str | Path, max_chars: int = 1200, overlap: int = 150) -> list[Chunk]:
    folder = Path(folder)
    out: list[Chunk] = []
    for path in sorted(list(folder.rglob("*.md")) + list(folder.rglob("*.txt"))):
        raw = path.read_text(encoding="utf-8", errors="replace")
        lines = raw.splitlines()
        acl: tuple[str, ...] = ("public",)
        if lines and (m := _ACL_RE.match(lines[0])):
            acl = tuple(sorted(g.strip().lower() for g in m.group(1).split(",") if g.strip()))
            raw = "\n".join(lines[1:])
        raw = _TEMPLATE_TAG_RE.sub("", raw)          # GitBook/Liquid tags such as {% hint %}
        doc_id = path.relative_to(folder).with_suffix("").as_posix()
        for s_idx, (title, body) in enumerate(_split_sections(raw)):
            for c_idx, piece in enumerate(chunk_text(body, max_chars, overlap)):
                out.append(Chunk(f"{doc_id}#{s_idx}.{c_idx}", doc_id, title or doc_id, piece, acl))
    if not out:
        raise ValueError(f"no .md or .txt content found under {folder}")
    return out


def save_chunks(chunks: list[Chunk], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)   # data/ subfolders are gitignored, so absent in a fresh clone
    with open(path, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(asdict(c)) + "\n")


def load_chunks(path: str | Path) -> list[Chunk]:
    with open(path, encoding="utf-8") as f:
        return [Chunk(**{**d, "acl": tuple(d["acl"])}) for d in map(json.loads, f) if d]
