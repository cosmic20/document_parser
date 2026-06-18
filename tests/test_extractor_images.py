"""Tests for embedded-image extraction — soft-mask compositing and blank filtering.

Reproduces the real-world case where a PDF stores a figure as a black colour layer plus
a separate soft-mask (the visible shape lives in the mask). PyMuPDF's ``extract_image``
returns only the black layer, so the naive path emitted solid-black rectangles.
"""

from __future__ import annotations

import io

import fitz
import numpy as np
from PIL import Image, ImageDraw

from document_parser.extractor import PDFExtractor, _is_blank


def _rgba_png_bytes(draw_content: bool, size=(300, 200)) -> bytes:
    """A transparent-background RGBA PNG. With content: black text drawn via alpha."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))  # fully transparent
    if draw_content:
        d = ImageDraw.Draw(img)
        d.rectangle([40, 60, 260, 140], fill=(0, 0, 0, 255))  # opaque black shape
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _pdf_with_image(png_bytes: bytes) -> bytes:
    """One-page PDF with the given PNG placed on it (PyMuPDF splits it into base+smask)."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_image(fitz.Rect(50, 50, 350, 250), stream=png_bytes)
    out = doc.tobytes()
    doc.close()
    return out


def test_is_blank_detects_flat_and_content():
    blank = Image.new("RGB", (200, 200), (255, 255, 255))
    assert _is_blank(blank)

    content = Image.new("RGB", (200, 200), (255, 255, 255))
    ImageDraw.Draw(content).rectangle([20, 20, 180, 180], fill=(0, 0, 0))
    assert not _is_blank(content)


def test_softmask_image_is_composited_not_black():
    pdf = _pdf_with_image(_rgba_png_bytes(draw_content=True))
    pages = PDFExtractor(min_image_size=50).extract(pdf)

    imgs = pages[0].embedded_images
    assert len(imgs) == 1, "the masked figure should be extracted"

    arr = np.asarray(imgs[0].image.convert("RGB"))
    assert arr.mean() > 30, "must not be a solid-black rectangle after compositing"
    # white background preserved where the mask was transparent
    assert (arr > 250).all(axis=2).mean() > 0.2


def test_blank_masked_image_is_dropped():
    pdf = _pdf_with_image(_rgba_png_bytes(draw_content=False))
    pages = PDFExtractor(min_image_size=50).extract(pdf)
    assert pages[0].embedded_images == [], "an empty (all-transparent) tile is dropped"
