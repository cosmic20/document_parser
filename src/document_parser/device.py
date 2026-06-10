"""Device detection for Apple Silicon (MPS), CUDA, and CPU."""

from __future__ import annotations

import logging

logger = logging.getLogger("document_parser")


def get_device() -> str:
    """Detect the best available device: cuda > mps > cpu."""
    import torch

    if torch.cuda.is_available():
        logger.info("Using CUDA GPU")
        return "cuda"
    elif torch.backends.mps.is_available():
        logger.info("Using Apple Silicon MPS GPU")
        return "mps"
    else:
        logger.info("Using CPU (no GPU detected)")
        return "cpu"


def get_dtype(device: str):
    """Get appropriate dtype for the device."""
    import torch

    if device == "cuda":
        return torch.float16
    elif device == "mps":
        return torch.float16
    else:
        return torch.float32
