"""Parser orchestrator — smart routing between text layer and OCR, with image extraction."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from tqdm import tqdm

from document_parser.engine import ModelRegistry, PageResult, ParseResult
from document_parser.extractor import PDFExtractor, is_image_file

# Ensure model backends are registered
import document_parser.models  # noqa: F401

logger = logging.getLogger("document_parser")

DEFAULT_MODEL = "qwen-vl-3b"
TEXT_THRESHOLD = 10  # minimum chars to consider a text layer usable


class DocumentParser:
    """Main parser: extracts text and images from PDFs/images.

    Smart routing: uses the embedded text layer when available,
    falls back to an OCR model for scanned/handwritten pages.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        dpi: int = 200,
        text_threshold: int = TEXT_THRESHOLD,
        force_ocr: bool = False,
        min_image_size: int = 150,
        use_llm: bool = False,
    ):
        self.model_name = model
        self.force_ocr = force_ocr
        self.text_threshold = text_threshold
        self.use_llm = use_llm  # only honored by document backends (e.g. marker)
        self.extractor = PDFExtractor(dpi=dpi, min_image_size=min_image_size)

    def parse(
        self,
        source: str | Path | bytes,
        output_dir: str | Path | None = None,
        filename: str | None = None,
        progress: Callable[[dict], None] | None = None,
    ) -> ParseResult:
        """Parse a PDF or image file into structured text + images.

        ``progress``, when given, is called once per page with a small event dict
        (``type="page"``, page/total, source, chars, elapsed_ms) — used by the web UI to
        stream live progress. It does not affect the CLI's tqdm bar.
        """
        start = time.perf_counter()

        # Determine filename
        if filename is None:
            if isinstance(source, (str, Path)):
                filename = Path(source).name
            else:
                filename = "document.pdf"

        # Set up output directory for images
        images_dir = None
        if output_dir is not None:
            images_dir = Path(output_dir) / "images"
            images_dir.mkdir(parents=True, exist_ok=True)

        # Document-level backends (e.g. marker) own the whole document: they do their
        # own rendering, routing, and image extraction. Bypass the per-page loop.
        if ModelRegistry.kind(self.model_name) == "document":
            return self._parse_document(source, filename, images_dir, start)

        # Extract pages
        logger.info(f"Extracting pages from {filename}...")
        extract_start = time.perf_counter()

        source_path = Path(source) if isinstance(source, (str, Path)) else source
        if isinstance(source_path, Path) and is_image_file(source_path):
            pages = self.extractor.extract_image(source_path)
        else:
            pages = self.extractor.extract(source)

        extract_ms = (time.perf_counter() - extract_start) * 1000
        logger.info(f"Extracted {len(pages)} pages in {extract_ms:.0f}ms")

        # Process each page
        results: list[PageResult] = []
        ocr_page_count = 0
        text_layer_count = 0
        total_images = 0
        engine = None  # lazy load only if needed

        # Progress bar with live ETA over the per-page OCR loop. Per-page detail is
        # demoted to DEBUG (shown with -v) so it doesn't clobber the bar by default.
        page_bar = tqdm(pages, desc="Parsing pages", unit="page")
        for extracted_page in page_bar:
            page_num = extracted_page.page_num

            # Save embedded images
            image_refs = []
            for emb_img in extracted_page.embedded_images:
                ref = {
                    "id": emb_img.id,
                    "width": emb_img.width,
                    "height": emb_img.height,
                }
                if images_dir is not None:
                    img_path = images_dir / f"{emb_img.id}.png"
                    emb_img.image.save(img_path, "PNG")
                    ref["path"] = str(img_path)
                image_refs.append(ref)
                total_images += 1

            # Smart routing: use text layer or fall back to OCR
            use_ocr = self.force_ocr or len(extracted_page.text.strip()) < self.text_threshold

            if use_ocr:
                # Lazy-load the OCR engine
                if engine is None:
                    logger.info(f"Loading OCR engine: {self.model_name}")
                    engine = ModelRegistry.get(self.model_name)
                    engine.ensure_loaded()

                logger.debug(f"  Page {page_num}/{len(pages)}: running OCR ({self.model_name})...")
                result = engine.run_timed(extracted_page.image, page_num)
                result.images = image_refs
                logger.debug(
                    f"  Page {page_num}/{len(pages)}: OCR done "
                    f"({len(result.text)} chars, {result.elapsed_ms:.0f}ms)"
                )
                page_bar.set_postfix_str(
                    f"p{page_num} OCR {len(result.text)}c {result.elapsed_ms:.0f}ms"
                )
                ocr_page_count += 1
            else:
                logger.debug(
                    f"  Page {page_num}/{len(pages)}: text layer "
                    f"({len(extracted_page.text.strip())} chars)"
                )
                page_bar.set_postfix_str(
                    f"p{page_num} text-layer {len(extracted_page.text.strip())}c"
                )
                result = PageResult(
                    page=page_num,
                    text=extracted_page.text.strip(),
                    source="text_layer",
                    images=image_refs,
                )
                text_layer_count += 1

            results.append(result)

            if progress is not None:
                progress(
                    {
                        "type": "page",
                        "page": page_num,
                        "total": len(pages),
                        "source": result.source,
                        "chars": len(result.text),
                        "elapsed_ms": round(result.elapsed_ms, 1),
                    }
                )

        page_bar.close()

        elapsed = (time.perf_counter() - start) * 1000

        logger.info(
            f"Done: {len(results)} pages "
            f"({text_layer_count} text layer, {ocr_page_count} OCR), "
            f"{total_images} images, {elapsed:.0f}ms"
        )

        return ParseResult(
            filename=filename,
            pages=results,
            metadata={
                "total_pages": len(results),
                "ocr_pages": ocr_page_count,
                "text_layer_pages": text_layer_count,
                "images_extracted": total_images,
                "model": self.model_name,
                "force_ocr": self.force_ocr,
                "elapsed_ms": round(elapsed, 1),
            },
        )

    def _parse_document(
        self,
        source: str | Path | bytes,
        filename: str,
        images_dir: Path | None,
        start: float,
    ) -> ParseResult:
        """Delegate the whole document to a document-level backend (e.g. marker)."""
        logger.info(f"Loading document engine: {self.model_name}")
        engine = ModelRegistry.get(self.model_name)
        engine.use_llm = self.use_llm
        engine.ensure_loaded()

        logger.info(f"Running {self.model_name} on the whole document...")
        pages = engine.run_document(source, images_dir)

        total_images = sum(len(p.images) for p in pages)
        elapsed = (time.perf_counter() - start) * 1000

        logger.info(
            f"Done: {len(pages)} pages, {total_images} images, {elapsed:.0f}ms "
            f"(via {self.model_name})"
        )

        return ParseResult(
            filename=filename,
            pages=pages,
            metadata={
                # marker does its own text-layer/OCR routing internally, so the
                # text_layer-vs-OCR split isn't meaningful here.
                "total_pages": len(pages),
                "ocr_pages": len(pages),
                "text_layer_pages": 0,
                "images_extracted": total_images,
                "model": self.model_name,
                "use_llm": self.use_llm,
                "force_ocr": self.force_ocr,
                "elapsed_ms": round(elapsed, 1),
            },
        )
