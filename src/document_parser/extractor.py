"""PDF text extraction, page rendering, and embedded image extraction using PyMuPDF."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image


@dataclass
class ExtractedPage:
    """Raw extraction result for a single PDF page."""

    page_num: int
    text: str  # text from the embedded text layer
    image: Image.Image  # rendered page as an image (for OCR fallback)
    embedded_images: list[EmbeddedImage] = field(default_factory=list)

    @property
    def has_text(self) -> bool:
        """Whether the text layer has meaningful content."""
        stripped = self.text.strip()
        return len(stripped) > 0


@dataclass
class EmbeddedImage:
    """An image embedded in a PDF page."""

    page_num: int
    index: int
    image: Image.Image
    width: int
    height: int

    @property
    def id(self) -> str:
        return f"p{self.page_num}_img{self.index}"


class PDFExtractor:
    """Extract text, page images, and embedded images from PDFs."""

    def __init__(self, dpi: int = 200, min_image_size: int = 150):
        self.dpi = dpi
        self.min_image_size = min_image_size  # skip tiny images (icons, bullets)

    def extract(self, source: str | Path | bytes) -> list[ExtractedPage]:
        """Extract all pages from a PDF file or bytes."""
        if isinstance(source, (str, Path)):
            doc = fitz.open(str(source))
        else:
            doc = fitz.open(stream=source, filetype="pdf")

        pages = []
        try:
            for page_num in range(doc.page_count):
                page = doc[page_num]
                extracted = self._extract_page(page, page_num + 1)
                pages.append(extracted)
        finally:
            doc.close()

        return pages

    def extract_image(self, source: str | Path | bytes) -> list[ExtractedPage]:
        """Wrap a single image file as an ExtractedPage (no text layer)."""
        if isinstance(source, bytes):
            img = Image.open(io.BytesIO(source))
        else:
            img = Image.open(source)

        img = img.convert("RGB")
        return [
            ExtractedPage(
                page_num=1,
                text="",
                image=img,
                embedded_images=[],
            )
        ]

    def _extract_page(self, page: fitz.Page, page_num: int) -> ExtractedPage:
        """Extract text, render image, and pull embedded images from a single page."""
        # Text layer
        text = page.get_text("text")

        # Render page to image
        zoom = self.dpi / 72  # 72 is PDF default DPI
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix)
        page_image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)

        # Embedded images
        embedded = self._extract_embedded_images(page, page_num)

        return ExtractedPage(
            page_num=page_num,
            text=text,
            image=page_image,
            embedded_images=embedded,
        )

    def _extract_embedded_images(self, page: fitz.Page, page_num: int) -> list[EmbeddedImage]:
        """Extract embedded images from a page, filtering out tiny and blank ones."""
        images = []
        image_list = page.get_images(full=True)
        doc = page.parent

        for idx, img_info in enumerate(image_list):
            xref = img_info[0]
            smask = img_info[1]  # soft-mask xref (0 if none)
            try:
                img = self._load_image(doc, xref, smask)
                if img is None:
                    continue

                # Skip tiny images (icons, decorations)
                if img.width < self.min_image_size or img.height < self.min_image_size:
                    continue

                # Skip blank tiles. Many PDFs store figures as black-on-transparent
                # with the real shape in a soft-mask; once composited some are simply
                # empty. Dropping them avoids emitting useless near-white rectangles.
                if _is_blank(img):
                    continue

                images.append(
                    EmbeddedImage(
                        page_num=page_num,
                        index=idx,
                        image=img,
                        width=img.width,
                        height=img.height,
                    )
                )
            except Exception:
                # Skip images that can't be extracted (JBIG2, etc.)
                continue

        return images

    @staticmethod
    def _load_image(doc: fitz.Document, xref: int, smask: int) -> Image.Image | None:
        """Load an embedded image as RGB, applying its soft-mask over a white background.

        PyMuPDF's ``extract_image`` returns only the base colour layer; for images drawn
        black-on-transparent (the visible shape encoded in a separate soft-mask) that
        layer is a solid black rectangle. We rebuild the pixmap, drop the image's own
        constant alpha, then composite the real soft-mask as the alpha channel.
        """
        pix = fitz.Pixmap(doc, xref)
        if pix.colorspace is not None and pix.colorspace.n == 4:  # CMYK → RGB
            pix = fitz.Pixmap(fitz.csRGB, pix)

        mode = "RGBA" if pix.alpha else "RGB"
        rgb = Image.frombytes(mode, (pix.width, pix.height), pix.samples).convert("RGB")

        if smask > 0:
            mask_pix = fitz.Pixmap(doc, smask)
            alpha = Image.frombytes("L", (mask_pix.width, mask_pix.height), mask_pix.samples)
            if alpha.size != rgb.size:
                alpha = alpha.resize(rgb.size)
            flattened = Image.new("RGB", rgb.size, (255, 255, 255))
            flattened.paste(rgb, mask=alpha)
            return flattened

        return rgb


def _is_blank(img: Image.Image, tol: int = 6, max_content: float = 0.002) -> bool:
    """True when an image is effectively a single flat colour (e.g. an empty tile).

    Compares every pixel against the most common corner colour; if almost none differ
    by more than ``tol`` per channel, it carries no real content.
    """
    import numpy as np

    arr = np.asarray(img.convert("RGB"), dtype=np.int16)
    bg = arr[0, 0]
    differs = (np.abs(arr - bg).max(axis=2) > tol)
    return float(differs.mean()) < max_content


def is_image_file(path: str | Path) -> bool:
    """Check if a file is an image based on extension."""
    return Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}
