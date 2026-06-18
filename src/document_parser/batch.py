"""Batch processing — turn folders of class PDFs into per-document JSON + a status index.

Input is one folder per class (a standalone top-level folder). The folder name is the course and
each PDF filename is the lecture title (normalized, overridable). Each document is processed with a
declared/suggested engine and recorded in a ``batch_index.json`` whose ``status`` field
(``pending → processed → integrated``) is the queue the vault integrator (Part B) drains.

The engine routing is manifest-driven: ``batch init`` scaffolds a ``batch.toml`` per class folder
that the user edits; ``batch run`` executes it (a manifest is optional — without one everything is
derived from the folder layout).
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:  # py3.11+ has tomllib; the project targets 3.10, so fall back to tomli
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - depends on interpreter version
    import tomli as tomllib

from document_parser.engine import ModelRegistry
from document_parser.parser import DEFAULT_MODEL, TEXT_THRESHOLD, DocumentParser

logger = logging.getLogger("document_parser")

PARSED_DIRNAME = "_parsed"
INDEX_FILENAME = "batch_index.json"
MANIFEST_FILENAME = "batch.toml"

# Filenames that carry no human-meaningful title (scanner/camera/export defaults), e.g.
# "scan0007", "IMG_2025_03_14", "DSC-1234", "2025-03-14".
_SCANISH = re.compile(
    r"^(scan|img|image|photo|dsc|doc|document|untitled|page)[\s_-]*\d[\d\s_-]*$", re.I
)
_DATEISH = re.compile(r"^\d{4}[-_]\d{2}[-_]\d{2}([\s_-].*)?$")


# --------------------------------------------------------------------------- models


@dataclass
class DocEntry:
    """One document's manifest entry (engine routing + provenance title)."""

    file: str
    title: str
    engine: str


@dataclass
class BatchManifest:
    course: str
    default_engine: str
    documents: list[DocEntry] = field(default_factory=list)


@dataclass
class IndexEntry:
    """One row of ``batch_index.json`` — the producer/consumer record + engine 'mark'."""

    path: str  # source pdf path, relative to the class folder
    course: str
    title: str
    engine: str
    json_path: str | None = None
    pages: int = 0
    images: int = 0
    status: str = "pending"  # pending | processed | integrated
    elapsed_ms: float = 0.0


# ------------------------------------------------------------------------- helpers


def normalize_title(stem: str) -> str:
    """Turn a (possibly messy) filename stem into a readable lecture-title suggestion.

    Underscores/hyphens become spaces, runs collapse, and all-lowercase words are capitalized
    while existing acronyms/mixed case are preserved. Scanner/camera default names are left as a
    cleaned stem for the user to override — there's nothing meaningful to recover from them.
    """
    s = stem.strip().replace("_", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return stem
    words = [w if not w.islower() else w.capitalize() for w in s.split(" ")]
    return " ".join(words)


def is_messy_filename(stem: str) -> bool:
    """Whether a stem looks like a scanner/camera default with no meaningful title."""
    return bool(_SCANISH.match(stem.strip()) or _DATEISH.match(stem.strip()))


def suggest_engine(pdf_path: Path, text_threshold: int = TEXT_THRESHOLD) -> str:
    """Suggest an engine from a cheap text-layer probe: typeset → marker, else → qwen.

    Mirrors the parser's per-page routing heuristic (``TEXT_THRESHOLD``) but at the document
    level and without rendering: a PDF whose pages mostly carry a usable text layer is typeset
    (marker shines), otherwise it is scanned/handwritten (a vision model reads it better).
    """
    import fitz  # PyMuPDF

    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return DEFAULT_MODEL
    try:
        n = doc.page_count
        if n == 0:
            return DEFAULT_MODEL
        with_text = sum(1 for i in range(n) if len(doc[i].get_text().strip()) >= text_threshold)
    finally:
        doc.close()
    return "marker" if with_text >= max(1, n // 2) else "qwen-vl-3b"


def list_pdfs(folder: Path) -> list[Path]:
    """The class folder's PDFs (sorted), excluding our own _parsed/ output dir."""
    return sorted(
        p for p in folder.glob("*.pdf") if PARSED_DIRNAME not in p.parts and p.is_file()
    )


# ------------------------------------------------------------------------ manifest


def scaffold_manifest(folder: Path) -> BatchManifest:
    """Build a manifest by scanning the folder: course = folder name, per-PDF title + engine."""
    docs = [
        DocEntry(
            file=pdf.name,
            title=normalize_title(pdf.stem),
            engine=suggest_engine(pdf),
        )
        for pdf in list_pdfs(folder)
    ]
    # Default engine = the majority suggestion, so a homogeneous class needs no per-file edits.
    default = max(("marker", "qwen-vl-3b"), key=lambda e: sum(d.engine == e for d in docs)) if docs else DEFAULT_MODEL
    return BatchManifest(course=folder.name, default_engine=default, documents=docs)


def load_manifest(folder: Path) -> BatchManifest | None:
    """Load ``batch.toml`` from a class folder, if present."""
    path = folder / MANIFEST_FILENAME
    if not path.exists():
        return None
    with open(path, "rb") as f:
        data = tomllib.load(f)
    docs = [
        DocEntry(
            file=d["file"],
            title=d.get("title") or normalize_title(Path(d["file"]).stem),
            engine=d.get("engine", ""),
        )
        for d in data.get("documents", [])
    ]
    return BatchManifest(
        course=data.get("course", folder.name),
        default_engine=data.get("default_engine", DEFAULT_MODEL),
        documents=docs,
    )


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def render_manifest_toml(manifest: BatchManifest) -> str:
    """Render a manifest to TOML by hand (stdlib has no writer; our format is simple)."""
    lines = [
        f'course = "{_toml_escape(manifest.course)}"',
        f'default_engine = "{_toml_escape(manifest.default_engine)}"',
        "",
    ]
    for d in manifest.documents:
        lines += [
            "[[documents]]",
            f'file = "{_toml_escape(d.file)}"',
            f'title = "{_toml_escape(d.title)}"',
            f'engine = "{_toml_escape(d.engine)}"',
            "",
        ]
    return "\n".join(lines)


def write_manifest(folder: Path, manifest: BatchManifest) -> Path:
    path = folder / MANIFEST_FILENAME
    path.write_text(render_manifest_toml(manifest))
    return path


# --------------------------------------------------------------------------- index


def index_path(folder: Path) -> Path:
    return folder / PARSED_DIRNAME / INDEX_FILENAME


def load_index(folder: Path) -> dict[str, IndexEntry]:
    """Load the batch index keyed by source filename; empty if none yet."""
    path = index_path(folder)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {e["path"]: IndexEntry(**e) for e in raw.get("documents", [])}


def save_index(folder: Path, course: str, entries: dict[str, IndexEntry]) -> Path:
    path = index_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "course": course,
        "documents": [asdict(e) for e in entries.values()],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return path


# ----------------------------------------------------------------------------- run


def resolve_engine(doc: DocEntry, manifest: BatchManifest, override: str | None) -> str:
    """Engine precedence: CLI override > per-file manifest engine > manifest default."""
    if override:
        return override
    if doc.engine:
        return doc.engine
    return manifest.default_engine


def run_folder(
    folder: Path,
    engine_override: str | None = None,
    force: bool = False,
    dpi: int = 200,
) -> dict[str, IndexEntry]:
    """Process every pending PDF in one class folder; update and persist its batch index.

    Idempotent: documents already ``processed``/``integrated`` are skipped unless ``force``.
    Returns the updated index entries.
    """
    folder = Path(folder)
    manifest = load_manifest(folder) or scaffold_manifest(folder)
    entries = load_index(folder)

    for doc in manifest.documents:
        src = folder / doc.file
        if not src.exists():
            logger.warning(f"  skipping {doc.file}: not found")
            continue

        existing = entries.get(doc.file)
        if existing and existing.status in ("processed", "integrated") and not force:
            logger.info(f"  skip {doc.file} (already {existing.status})")
            continue

        engine = resolve_engine(doc, manifest, engine_override)
        if engine not in ModelRegistry.available():
            raise ValueError(
                f"Unknown engine '{engine}' for {doc.file}. "
                f"Available: {', '.join(ModelRegistry.available())}"
            )

        out_dir = folder / PARSED_DIRNAME / src.stem
        out_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"  processing {doc.file} with {engine}...")
        start = time.perf_counter()
        parser = DocumentParser(model=engine, dpi=dpi)
        result = parser.parse(source=src, output_dir=out_dir)
        elapsed = (time.perf_counter() - start) * 1000

        json_path = out_dir / f"{src.stem}.json"
        json_path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))

        entries[doc.file] = IndexEntry(
            path=doc.file,
            course=manifest.course,
            title=doc.title,
            engine=engine,
            json_path=str(json_path.relative_to(folder)),
            pages=result.metadata.get("total_pages", 0),
            images=result.metadata.get("images_extracted", 0),
            status="processed",
            elapsed_ms=round(elapsed, 1),
        )
        # Persist after each doc so an interrupted run resumes cleanly.
        save_index(folder, manifest.course, entries)

    return entries
