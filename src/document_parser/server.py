"""FastAPI server — POST /parse, GET /health, GET /models."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Query, UploadFile
from fastapi.responses import JSONResponse

from document_parser.engine import ModelRegistry
from document_parser.parser import DEFAULT_MODEL, DocumentParser

# Ensure backends are registered
import document_parser.models  # noqa: F401

app = FastAPI(
    title="Document Parser",
    description="Handwriting-aware PDF/image OCR with pluggable model backends",
    version="0.1.0",
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/models")
async def list_models():
    return {"models": ModelRegistry.available(), "default": DEFAULT_MODEL}


@app.post("/parse")
async def parse_document(
    file: UploadFile = File(...),
    model: str = Query(default=DEFAULT_MODEL, description="OCR model backend to use"),
    force_ocr: bool = Query(default=False, description="Force OCR on all pages"),
    use_llm: bool = Query(
        default=False, description="Enable LLM augmentation (document backends like marker)"
    ),
    dpi: int = Query(default=200, ge=72, le=600, description="Render DPI for page images"),
    output_images: bool = Query(
        default=True, description="Whether to save extracted images to disk"
    ),
):
    """Parse a PDF or image file into structured text + images."""
    # Validate model
    if model not in ModelRegistry.available():
        return JSONResponse(
            status_code=400,
            content={
                "error": f"Unknown model '{model}'",
                "available": ModelRegistry.available(),
            },
        )

    # Read uploaded file
    content = await file.read()
    filename = file.filename or "upload.pdf"

    # Set up output dir for images
    output_dir = None
    if output_images:
        output_dir = Path(tempfile.mkdtemp(prefix="docparse_"))

    parser = DocumentParser(
        model=model,
        dpi=dpi,
        force_ocr=force_ocr,
        use_llm=use_llm,
    )

    result = parser.parse(source=content, output_dir=output_dir, filename=filename)

    return result.to_dict()
