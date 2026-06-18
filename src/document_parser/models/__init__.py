"""OCR model backends.

Importing this module registers all available engines with the ModelRegistry.
"""

# Register backends — import triggers the @register_engine decorators.
# These modules import their heavy deps (transformers, marker) lazily inside
# load(), so importing here is cheap and does not require optional extras.
from document_parser.models.got_ocr2 import GOTOCR2Engine  # noqa: F401
from document_parser.models.marker import MarkerEngine  # noqa: F401
from document_parser.models.qwen_vl import QwenVL3BEngine, QwenVL7BEngine  # noqa: F401
