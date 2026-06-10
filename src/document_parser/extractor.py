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
        """Extract embedded images from a page, filtering out tiny ones."""
        images = []
        image_list = page.get_images(full=True)

        for idx, img_info in enumerate(image_list):
            xref = img_info[0]
            try:
                base_image = page.parent.extract_image(xref)
                if base_image is None:
                    continue

                image_bytes = base_image["image"]
                img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

                # Skip tiny images (icons, decorations)
                if img.width < self.min_image_size or img.height < self.min_image_size:
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


def is_image_file(path: str | Path) -> bool:
    """Check if a file is an image based on extension."""
    return Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}
