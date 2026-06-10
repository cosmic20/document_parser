"""OCR model backends.

Importing this module registers all available engines with the ModelRegistry.
"""

# Register backends — import triggers the @register_engine decorators
from document_parser.models.got_ocr2 import GOTOCR2Engine  # noqa: F401
from document_parser.models.qwen_vl import QwenVL3BEngine, QwenVL7BEngine  # noqa: F401
