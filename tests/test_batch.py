"""Tests for the batch pipeline — offline, no model downloads.

A stub OCR engine is registered so the run loop exercises the real DocumentParser path on a
synthetic PDF without loading any weights. Title normalization and the engine-suggestion
heuristic are pure and tested directly.
"""

from __future__ import annotations

import json

import fitz
import pytest

from document_parser import batch as b
from document_parser.engine import OCREngine, register_engine


@register_engine("stub-ocr")
class _StubOCR(OCREngine):
    def load(self) -> None:  # no weights
        pass

    def run(self, image) -> str:
        return "stub ocr text"


def _make_pdf(path, text: str | None = None, pages: int = 1) -> None:
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


# ------------------------------------------------------------------ pure helpers


@pytest.mark.parametrize(
    "stem,expected",
    [
        ("week05b-cdfs-pdfs", "Week05b Cdfs Pdfs"),
        ("Lecture 3 - CDFs", "Lecture 3 CDFs"),  # acronym preserved, not "Cdfs"
        ("intro_to_probability", "Intro To Probability"),
        ("Random Variables", "Random Variables"),  # already clean, unchanged
    ],
)
def test_normalize_title(stem, expected):
    assert b.normalize_title(stem) == expected


def test_is_messy_filename():
    assert b.is_messy_filename("scan0007")
    assert b.is_messy_filename("IMG_2025_03_14")
    assert b.is_messy_filename("2025-03-14")
    assert not b.is_messy_filename("Lecture 3 - CDFs")


def test_suggest_engine_typeset_vs_scanned(tmp_path):
    typeset = tmp_path / "typeset.pdf"
    _make_pdf(typeset, text="A full paragraph of typeset lecture text here. " * 5)
    scanned = tmp_path / "scanned.pdf"
    _make_pdf(scanned, text=None)  # no text layer

    assert b.suggest_engine(typeset) == "marker"
    assert b.suggest_engine(scanned) == "qwen-vl-3b"


def test_resolve_engine_precedence():
    man = b.BatchManifest(course="c", default_engine="marker", documents=[])
    doc = b.DocEntry(file="f.pdf", title="F", engine="got-ocr2")
    assert b.resolve_engine(doc, man, "qwen-vl-3b") == "qwen-vl-3b"  # CLI override wins
    assert b.resolve_engine(doc, man, None) == "got-ocr2"  # per-file manifest engine
    assert b.resolve_engine(b.DocEntry("f.pdf", "F", ""), man, None) == "marker"  # default


# ----------------------------------------------------------------- manifest I/O


def test_scaffold_and_manifest_roundtrip(tmp_path):
    cls = tmp_path / "21-325 Probability"
    cls.mkdir()
    _make_pdf(cls / "scan0007.pdf", text="lots of typeset text " * 10)

    man = b.scaffold_manifest(cls)
    assert man.course == "21-325 Probability"  # course derived from folder name
    assert len(man.documents) == 1
    assert man.documents[0].engine == "marker"  # has a text layer

    b.write_manifest(cls, man)
    loaded = b.load_manifest(cls)
    assert loaded.course == man.course
    assert loaded.documents[0].file == "scan0007.pdf"
    assert loaded.documents[0].title == man.documents[0].title


# ----------------------------------------------------------------------- run loop


def test_run_folder_processes_marks_and_resumes(tmp_path):
    cls = tmp_path / "ML"
    cls.mkdir()
    _make_pdf(cls / "lec1.pdf", text=None)  # no text layer → OCR path → stub engine
    man = b.BatchManifest(
        course="ML",
        default_engine="stub-ocr",
        documents=[b.DocEntry("lec1.pdf", "Lecture 1", "stub-ocr")],
    )
    b.write_manifest(cls, man)

    entries = b.run_folder(cls)
    e = entries["lec1.pdf"]
    assert e.status == "processed"
    assert e.engine == "stub-ocr"  # the engine "mark"
    assert e.course == "ML" and e.title == "Lecture 1"

    jp = cls / e.json_path
    assert jp.exists()
    data = json.loads(jp.read_text())
    assert data["metadata"]["model"] == "stub-ocr"
    assert b.index_path(cls).exists()

    # Idempotent: a re-run without --force skips, so a deleted output is NOT recreated.
    jp.unlink()
    b.run_folder(cls)
    assert not jp.exists()

    # --force reprocesses, recreating the output.
    b.run_folder(cls, force=True)
    assert jp.exists()


def test_external_source_outputs_to_work_dir(tmp_path):
    # Registered class: PDFs live in an external source; outputs must land in the work dir,
    # leaving the source folder pristine.
    ext = tmp_path / "src"
    ext.mkdir()
    _make_pdf(ext / "lec1.pdf", text=None)
    work = tmp_path / "work"
    work.mkdir()
    b.write_manifest(work, b.scaffold_manifest(work, source=ext))

    assert b.load_manifest(work).source == str(ext)
    assert b.source_dir(work) == ext

    entries = b.run_folder(work, engine_override="stub-ocr")
    assert entries["lec1.pdf"].status == "processed"
    assert (work / "_parsed" / "lec1" / "lec1.json").exists()  # output in work dir
    assert not (ext / "_parsed").exists()  # source untouched


def test_run_folder_without_manifest_derives_everything(tmp_path):
    cls = tmp_path / "Optimization"
    cls.mkdir()
    _make_pdf(cls / "gradient_descent.pdf", text="typeset optimization notes " * 8)

    # No batch.toml: course from folder, title normalized from filename, engine from --engine.
    entries = b.run_folder(cls, engine_override="stub-ocr")
    e = entries["gradient_descent.pdf"]
    assert e.course == "Optimization"
    assert e.title == "Gradient Descent"
    assert e.engine == "stub-ocr"
    assert e.status == "processed"
