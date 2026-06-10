"""Qwen2.5-VL backends — optional higher-quality OCR engines.

Install with: uv sync --extra qwen
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from document_parser.engine import OCREngine, register_engine

if TYPE_CHECKING:
    from PIL import Image

logger = logging.getLogger("document_parser")

SYSTEM_PROMPT = (
    "You are a precise OCR assistant. Extract all visible text from the image exactly as written. "
    "Preserve line breaks and structure. Do not summarize, interpret, or add any commentary. "
    "Output only the extracted text."
)


class QwenVLBase(OCREngine):
    """Base class for Qwen2.5-VL backends."""

    model_id: str = ""

    def __init__(self):
        self.model = None
        self.processor = None
        self.device = None

    def load(self) -> None:
        try:
            from qwen_vl_utils import process_vision_info
        except ImportError:
            raise ImportError(
                "Qwen VL backend requires extra dependencies. "
                "Install with: uv sync --extra qwen"
            )

        from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

        import torch

        from document_parser.device import get_device

        self.device = get_device()
        # Use bfloat16 on MPS/CUDA — float16 overflows in Qwen's vision encoder
        # causing inf/nan in logits during generation
        dtype = torch.bfloat16 if self.device in ("mps", "cuda") else torch.float32

        logger.info(f"Loading {self.model_id} on {self.device} ({dtype})...")

        self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            self.model_id,
            torch_dtype=dtype,
        )

        self.model = self.model.to(self.device)
        self.processor = AutoProcessor.from_pretrained(
            self.model_id,
            min_pixels=256 * 28 * 28,   # ~200K pixels
            max_pixels=1280 * 28 * 28,  # ~1M pixels — caps memory for vision attention
        )
        self.process_vision_info = process_vision_info
        self.model.eval()
        logger.info(f"{self.model_id} loaded.")

    def run(self, image: Image.Image) -> str:
        self.ensure_loaded()

        messages = [
            {
                "role": "system",
                "content": [{"type": "text", "text": SYSTEM_PROMPT}],
            },
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": "Extract all text from this image."},
                ],
            },
        ]

        text_input = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = self.process_vision_info(messages)

        inputs = self.processor(
            text=[text_input],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        ).to(self.device)

        import torch

        with torch.no_grad():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=2048,
                do_sample=False,
                repetition_penalty=1.3,
                no_repeat_ngram_size=12,
            )

        generated = output_ids[0, inputs.input_ids.shape[1] :]
        result = self.processor.decode(generated, skip_special_tokens=True)

        return result.strip()


@register_engine("qwen-vl-3b")
class QwenVL3BEngine(QwenVLBase):
    """Qwen2.5-VL-3B — ~6GB memory. Good fit for 12-16GB Apple Silicon."""

    model_id = "Qwen/Qwen2.5-VL-3B-Instruct"


@register_engine("qwen-vl-7b")
class QwenVL7BEngine(QwenVLBase):
    """Qwen2.5-VL-7B — ~14GB memory. Needs 16GB+ RAM/VRAM."""

    model_id = "Qwen/Qwen2.5-VL-7B-Instruct"
