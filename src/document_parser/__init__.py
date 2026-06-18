"""Document Parser — handwriting-aware PDF/image OCR with pluggable model backends."""

__version__ = "0.1.0"

from document_parser.engine import (
    BaseEngine,
    DocumentEngine,
    ModelRegistry,
    OCREngine,
    PageResult,
    ParseResult,
)
from document_parser.extractor import PDFExtractor
from document_parser.parser import DocumentParser

__all__ = [
    "DocumentParser",
    "PDFExtractor",
    "BaseEngine",
    "OCREngine",
    "DocumentEngine",
    "ModelRegistry",
    "PageResult",
    "ParseResult",
]
