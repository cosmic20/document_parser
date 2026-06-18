"""Tests for the marker document backend — mapping logic exercised offline.

The marker library itself is an optional extra and downloads large models, so these
tests monkeypatch the converter and feed a synthetic marker JSON tree. They validate
the adapter (per-page grouping, content-ref resolution, text flattening, image
extraction) without installing or running marker.
"""

from __future__ import annotations

import base64
import importlib.util
import io

import pytest
from PIL import Image

from document_parser.engine import ModelRegistry, PageResult, ParseResult
from document_parser.models.marker import MarkerEngine

MARKER_INSTALLED = importlib.util.find_spec("marker") is not None


def _png_b64(color=(255, 0, 0), size=(8, 8)) -> str:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


class _FakeRendered:
    def __init__(self, doc: dict):
        self._doc = doc

    def model_dump(self, **kwargs) -> dict:
        # Real marker JSONOutput requires mode="json" to serialize (its metadata holds a
        # dict used as a mapping key, which python-mode hashing rejects). Assert the
        # adapter passes it so this stays a regression guard.
        assert kwargs.get("mode") == "json"
        return self._doc


def _fake_marker_doc() -> dict:
    return {
        "block_type": "Document",
        "children": [
            {
                "id": "/page/0/Page/0",
                "block_type": "Page",
                "bbox": [0, 0, 612, 792],
                "html": (
                    "<content-ref src='/page/0/PageHeader/1'></content-ref>"
                    "<content-ref src='/page/0/SectionHeader/2'></content-ref>"
                    "<content-ref src='/page/0/Text/3'></content-ref>"
                ),
                "images": {},
                "children": [
                    {
                        "id": "/page/0/PageHeader/1",
                        "block_type": "PageHeader",
                        "bbox": [0, 0, 612, 30],
                        "html": "<p>running head</p>",
                        "children": None,
                        "images": {},
                    },
                    {
                        "id": "/page/0/SectionHeader/2",
                        "block_type": "SectionHeader",
                        "bbox": [0, 40, 612, 70],
                        "html": "<h1>Gradient Descent</h1>",
                        "children": None,
                        "images": {},
                    },
                    {
                        "id": "/page/0/Figure/3",
                        "block_type": "Figure",
                        "bbox": [0, 80, 612, 400],
                        "html": "<p>figure</p>",
                        "children": None,
                        "images": {"/page/0/Figure/3": _png_b64()},
                    },
                ],
            }
        ],
    }


def _loaded_engine(monkeypatch) -> MarkerEngine:
    engine = MarkerEngine()
    engine._loaded = True  # skip real model loading
    engine.models = {}
    monkeypatch.setattr(engine, "_convert", lambda path: _FakeRendered(_fake_marker_doc()))
    return engine


def test_registered_as_document_backend():
    assert "marker" in ModelRegistry.available()
    assert ModelRegistry.kind("marker") == "document"


def test_run_document_maps_pages_and_blocks(monkeypatch):
    engine = _loaded_engine(monkeypatch)
    pages = engine.run_document("dummy.pdf", images_dir=None)

    assert len(pages) == 1
    page = pages[0]
    assert isinstance(page, PageResult)
    assert page.page == 1
    assert page.source == "marker"

    block_types = [b["block_type"] for b in page.blocks]
    assert block_types == ["PageHeader", "SectionHeader", "Figure"]
    # resolved html is carried verbatim per block
    assert page.blocks[1]["html"] == "<h1>Gradient Descent</h1>"


def test_text_flatten_drops_header_footer(monkeypatch):
    engine = _loaded_engine(monkeypatch)
    page = engine.run_document("dummy.pdf", images_dir=None)[0]
    assert "running head" not in page.text  # PageHeader dropped
    assert "Gradient Descent" in page.text


def test_images_saved_to_disk(monkeypatch, tmp_path):
    engine = _loaded_engine(monkeypatch)
    page = engine.run_document("dummy.pdf", images_dir=tmp_path)[0]

    assert len(page.images) == 1
    ref = page.images[0]
    assert ref["id"] == "p1_img0"
    assert ref["width"] == 8 and ref["height"] == 8
    saved = tmp_path / "p1_img0.png"
    assert saved.exists()


def test_structure_fields_emitted_only_for_document_pages():
    img_page = PageResult(page=1, text="t", source="qwen-vl-3b")
    doc = ParseResult("f.pdf", [img_page], {}).to_dict()
    assert "markdown" not in doc["pages"][0]
    assert "blocks" not in doc["pages"][0]


def test_per_page_elapsed_ms_emitted():
    page = PageResult(page=1, text="t", source="qwen-vl-3b", elapsed_ms=1234.56)
    doc = ParseResult("f.pdf", [page], {}).to_dict()
    assert doc["pages"][0]["elapsed_ms"] == 1234.6  # rounded to 1 decimal


@pytest.mark.skipif(MARKER_INSTALLED, reason="marker-pdf is installed")
def test_load_without_marker_raises_helpful_error():
    engine = MarkerEngine()
    with pytest.raises(ImportError, match="uv sync --extra marker"):
        engine.load()
