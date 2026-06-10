"""GOT-OCR2 backend — default OCR engine (580M params)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from document_parser.engine import OCREngine, register_engine

if TYPE_CHECKING:
    from PIL import Image

logger = logging.getLogger("document_parser")

MODEL_ID = "stepfun-ai/GOT-OCR-2.0-hf"


@register_engine("got-ocr2")
class GOTOCR2Engine(OCREngine):
    """OCR engine using GOT-OCR2 via HuggingFace Transformers.

    580M parameter unified OCR model. Handles typed text, handwriting,
    tables, formulas, and more. Runs on ~4GB VRAM or CPU.
    """

    def __init__(self):
        self.model = None
        self.processor = None
        self.device = None

    def load(self) -> None:
        from transformers import AutoModelForImageTextToText, AutoProcessor

        from document_parser.device import get_device, get_dtype

        self.device = get_device()
        dtype = get_dtype(self.device)

        logger.info(f"Loading GOT-OCR2 model on {self.device} ({dtype})...")

        self.processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)
        self.model = AutoModelForImageTextToText.from_pretrained(
            MODEL_ID,
            trust_remote_code=True,
            dtype=dtype,
        )

        self.model = self.model.to(self.device)
        self.model.eval()
        logger.info("GOT-OCR2 model loaded.")

    def run(self, image: Image.Image) -> str:
        self.ensure_loaded()

        inputs = self.processor(image, return_tensors="pt").to(self.device)

        import torch

        with torch.no_grad():
            generated_ids = self.model.generate(
                **inputs,
                do_sample=False,
                tokenizer=self.processor.tokenizer,
                stop_strings="<|im_end|>",
                max_new_tokens=4096,
                repetition_penalty=1.2,
                no_repeat_ngram_size=12,
            )

        # Trim input tokens from output
        input_len = inputs["input_ids"].shape[1]
        generated_ids = generated_ids[:, input_len:]
        result = self.processor.decode(generated_ids[0], skip_special_tokens=True)

        return result.strip()
