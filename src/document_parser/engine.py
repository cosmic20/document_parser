"""Abstract OCR engine interface and pluggable model registry."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image


@dataclass
class PageResult:
    """OCR result for a single page."""

    page: int
    text: str
    source: str  # "text_layer" or model name like "got-ocr2"
    images: list[dict] = field(default_factory=list)
    elapsed_ms: float = 0.0
    markdown: str | None = None  # structured markdown (document backends, e.g. marker)
    blocks: list[dict] | None = None  # structured block tree (document backends)


@dataclass
class ParseResult:
    """Full parse result for a document."""

    filename: str
    pages: list[PageResult]
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        pages = []
        for p in self.pages:
            page_dict = {
                "page": p.page,
                "text": p.text,
                "source": p.source,
                "images": p.images,
                "elapsed_ms": round(p.elapsed_ms, 1),
            }
            # Structured fields are only emitted when a document backend produced them,
            # keeping image-backend output byte-for-byte backward compatible.
            if p.markdown is not None:
                page_dict["markdown"] = p.markdown
            if p.blocks is not None:
                page_dict["blocks"] = p.blocks
            pages.append(page_dict)

        return {
            "filename": self.filename,
            "pages": pages,
            "metadata": self.metadata,
        }


class BaseEngine(ABC):
    """Shared base for all backends: named, lazily loaded, registry-tracked.

    ``kind`` tells the parser how to drive the backend:
      - ``"image"``  → an :class:`OCREngine`, called per page image.
      - ``"document"`` → a :class:`DocumentEngine`, handed the whole document.
    """

    name: str = "base"
    kind: str = "base"

    @abstractmethod
    def load(self) -> None:
        """Load model weights. Called lazily on first use."""
        ...

    @property
    def is_loaded(self) -> bool:
        return getattr(self, "_loaded", False)

    def ensure_loaded(self) -> None:
        if not self.is_loaded:
            self.load()
            self._loaded = True


class OCREngine(BaseEngine):
    """Abstract base class for image→text OCR model backends."""

    kind = "image"

    @abstractmethod
    def run(self, image: Image.Image) -> str:
        """Run OCR on a single page image, return extracted text."""
        ...

    def run_timed(self, image: Image.Image, page_num: int) -> PageResult:
        """Run OCR and return a PageResult with timing."""
        start = time.perf_counter()
        text = self.run(image)
        elapsed = (time.perf_counter() - start) * 1000
        return PageResult(page=page_num, text=text, source=self.name, elapsed_ms=elapsed)


class DocumentEngine(BaseEngine):
    """Abstract base class for whole-document pipeline backends (e.g. marker).

    Unlike :class:`OCREngine` (one page image in, one text string out), a document
    engine owns the entire document: it does its own page rendering, layout analysis,
    text/OCR routing, and image extraction, returning one PageResult per page —
    optionally with structured ``markdown`` / ``blocks``.
    """

    kind = "document"
    use_llm: bool = False

    @abstractmethod
    def run_document(
        self, source: str | Path | bytes, images_dir: Path | None
    ) -> list[PageResult]:
        """Process a whole document into per-page results.

        Implementations save any extracted images into ``images_dir`` (when not None)
        and populate each PageResult's ``images`` refs accordingly.
        """
        ...


class ModelRegistry:
    """Registry of available OCR engine backends."""

    _engines: dict[str, type[BaseEngine]] = {}
    _instances: dict[str, BaseEngine] = {}

    @classmethod
    def register(cls, name: str, engine_cls: type[BaseEngine]) -> None:
        cls._engines[name] = engine_cls

    @classmethod
    def kind(cls, name: str) -> str:
        """Return a backend's kind ("image" or "document") without instantiating it."""
        if name not in cls._engines:
            available = ", ".join(cls._engines.keys()) or "(none)"
            raise ValueError(f"Unknown model '{name}'. Available: {available}")
        return cls._engines[name].kind

    @classmethod
    def get(cls, name: str) -> BaseEngine:
        """Get or create an engine instance by name. Lazy-loads on first call."""
        if name not in cls._engines:
            available = ", ".join(cls._engines.keys()) or "(none)"
            raise ValueError(f"Unknown model '{name}'. Available: {available}")

        if name not in cls._instances:
            engine = cls._engines[name]()
            cls._instances[name] = engine

        return cls._instances[name]

    @classmethod
    def available(cls) -> list[str]:
        return list(cls._engines.keys())

    @classmethod
    def clear(cls) -> None:
        """Clear all instances (useful for testing)."""
        cls._instances.clear()


def register_engine(name: str):
    """Decorator to register an OCR engine class."""

    def decorator(cls: type[BaseEngine]) -> type[BaseEngine]:
        cls.name = name
        ModelRegistry.register(name, cls)
        return cls

    return decorator
