"""Vault concept index — a deterministic scan of an Obsidian vault's note frontmatter.

The (LLM) vault integrator reads this index to dedup concepts and resolve links without
re-reading every note as the vault grows, and to keep cross-topic links acyclic. The index
captures, per note, ``{title, aliases, topic, tags, path, sources}`` plus a derived
**topic-dependency graph** (``topic_edges``) built from the cross-topic ``[[links]]`` actually
present in the vault. ``would_create_cycle`` lets the integrator reject a new cross-topic link
that would reverse an existing dependency (see the ``vault-build`` skill).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

try:  # py3.11+ has tomllib; the project targets 3.10, so fall back to tomli
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - depends on interpreter version
    import tomli as tomllib

CONFIG_PATH = Path.home() / ".docparse.toml"
INDEX_FILENAME = ".vault-index.json"

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)
# [[Target]], [[Target|alias]], [[Target#heading]] → capture "Target"
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")


# --------------------------------------------------------------------------- config


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def _save_config(cfg: dict) -> None:
    """Write the whole config back, preserving every section (flat string tables)."""
    lines: list[str] = []
    for section, vals in cfg.items():
        lines.append(f"[{section}]")
        for k, v in vals.items():
            lines.append(f'{k} = "{v}"')
        lines.append("")
    CONFIG_PATH.write_text("\n".join(lines))


def _load_path(section: str) -> Path | None:
    p = _load_config().get(section, {}).get("path")
    return Path(p).expanduser() if p else None


def _save_path(section: str, path: Path) -> None:
    cfg = _load_config()
    cfg.setdefault(section, {})["path"] = str(Path(path).expanduser())
    _save_config(cfg)


def load_config_vault_path() -> Path | None:
    """Read the remembered vault path from ``~/.docparse.toml`` (``[vault] path``)."""
    return _load_path("vault")


def save_config_vault_path(path: Path) -> None:
    """Remember the vault path in ``~/.docparse.toml`` so it isn't retyped."""
    _save_path("vault", path)


def load_config_workspace_path() -> Path | None:
    """Read the remembered workspace root (where class folders live) from config."""
    return _load_path("workspace")


def save_config_workspace_path(path: Path) -> None:
    """Remember the workspace root in ``~/.docparse.toml``."""
    _save_path("workspace", path)


# ----------------------------------------------------------------------- note model


@dataclass
class NoteRecord:
    title: str
    topic: str | None
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    path: str = ""


# ------------------------------------------------------------------------ parsing


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter dict, body). Missing/invalid frontmatter yields ({}, full text)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(fm, dict):
        return {}, text
    return fm, text[m.end() :]


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [s.strip() for s in str(value).split(",") if s.strip()]


def topic_of(note_path: Path, vault_root: Path) -> str | None:
    """A note's topic = its first-level folder under the vault; None for root-level notes."""
    rel = note_path.relative_to(vault_root)
    return rel.parts[0] if len(rel.parts) > 1 else None


def extract_link_targets(body: str) -> set[str]:
    """All ``[[wikilink]]`` targets in a note body (alias/heading stripped)."""
    return {m.strip() for m in _WIKILINK_RE.findall(body)}


# -------------------------------------------------------------------- topic graph


def would_create_cycle(edges: dict[str, list[str]], src: str, dst: str) -> bool:
    """Whether adding edge ``src → dst`` would create a cycle (a path ``dst → … → src`` exists)."""
    if src == dst:
        return False  # within-topic links are always allowed
    seen: set[str] = set()
    queue: deque[str] = deque([dst])
    while queue:
        node = queue.popleft()
        if node == src:
            return True
        if node in seen:
            continue
        seen.add(node)
        queue.extend(edges.get(node, []))
    return False


# ----------------------------------------------------------------------- indexing


def build_index(vault: Path) -> dict:
    """Scan a vault into the concept index + derived topic-dependency graph."""
    vault = Path(vault)
    notes: list[NoteRecord] = []
    bodies: dict[str, str] = {}  # note title → body, for link extraction
    lookup: dict[str, str] = {}  # title/alias (lowercased) → topic, for resolving links

    for md in sorted(vault.rglob("*.md")):
        fm, body = split_frontmatter(md.read_text())
        title = md.stem
        topic = fm.get("topic") or topic_of(md, vault)
        rec = NoteRecord(
            title=title,
            topic=topic,
            aliases=_as_list(fm.get("aliases")),
            tags=_as_list(fm.get("tags")),
            sources=_as_list(fm.get("sources")),
            path=str(md.relative_to(vault)),
        )
        notes.append(rec)
        bodies[title] = body
        if topic:
            for key in [title, *rec.aliases]:
                lookup[key.lower()] = topic

    # Topic edges from cross-topic links actually present in note bodies.
    topic_edges: dict[str, set[str]] = defaultdict(set)
    for rec in notes:
        if not rec.topic:
            continue  # root-level notes (e.g. top MOC) don't anchor dependencies
        for target in extract_link_targets(bodies.get(rec.title, "")):
            target_topic = lookup.get(target.lower())
            if target_topic and target_topic != rec.topic:
                topic_edges[rec.topic].add(target_topic)

    return {
        "notes": [asdict(n) for n in notes],
        "topic_edges": {k: sorted(v) for k, v in sorted(topic_edges.items())},
    }


def write_index(vault: Path) -> tuple[Path, dict]:
    """Build the index and write it to ``<vault>/.vault-index.json``."""
    index = build_index(vault)
    out = Path(vault) / INDEX_FILENAME
    out.write_text(json.dumps(index, indent=2, ensure_ascii=False))
    return out, index
