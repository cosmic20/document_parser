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


@dataclass
class ParseResult:
    """Full parse result for a document."""

    filename: str
    pages: list[PageResult]
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "pages": [
                {
                    "page": p.page,
                    "text": p.text,
                    "source": p.source,
                    "images": p.images,
                }
                for p in self.pages
            ],
            "metadata": self.metadata,
        }


class OCREngine(ABC):
    """Abstract base class for OCR model backends."""

    name: str = "base"

    @abstractmethod
    def load(self) -> None:
        """Load model weights. Called lazily on first use."""
        ...

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

    @property
    def is_loaded(self) -> bool:
        return getattr(self, "_loaded", False)

    def ensure_loaded(self) -> None:
        if not self.is_loaded:
            self.load()
            self._loaded = True


class ModelRegistry:
    """Registry of available OCR engine backends."""

    _engines: dict[str, type[OCREngine]] = {}
    _instances: dict[str, OCREngine] = {}

    @classmethod
    def register(cls, name: str, engine_cls: type[OCREngine]) -> None:
        cls._engines[name] = engine_cls

    @classmethod
    def get(cls, name: str) -> OCREngine:
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

    def decorator(cls: type[OCREngine]) -> type[OCREngine]:
        cls.name = name
        ModelRegistry.register(name, cls)
        return cls

    return decorator
