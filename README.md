# Document Parser

Handwriting-aware PDF/image OCR service with pluggable HuggingFace model backends. Extracts text and images from PDFs into structured JSON so downstream AI agents can process the content (e.g., building an Obsidian vault).

## How it works

1. **Text layer check** — PyMuPDF tries to extract embedded text from each page. If a page has enough text (>50 chars by default), it's used directly — no model needed.
2. **OCR fallback** — Pages with little or no text (scanned documents, handwritten notes) are rendered to images and sent through an OCR model.
3. **Image extraction** — Embedded images (diagrams, figures, photos) are extracted and saved alongside the text.

## Installation

```bash
# Base install (GOT-OCR2 backend)
uv sync

# With Qwen2.5-VL backend (better handwriting accuracy, needs ~8GB VRAM)
uv sync --extra qwen

# Dev tools (pytest, ruff)
uv sync --extra dev
```

## Usage

### CLI

```bash
# Parse a PDF (uses text layer where possible, OCR for the rest)
docparse parse ./lecture.pdf

# Force OCR on all pages
docparse parse ./handwritten_notes.pdf --force-ocr

# Choose model and output format
docparse parse ./notes.pdf --model got-ocr2 --format markdown --output ./parsed/

# List available models
docparse models
```

### API

```bash
# Start the server
uvicorn document_parser.server:app --reload

# Parse a file
curl -X POST http://localhost:8000/parse \
  -F "file=@./lecture.pdf" \
  -G -d "model=got-ocr2"

# Check available models
curl http://localhost:8000/models
```

### Python

```python
from document_parser import DocumentParser

parser = DocumentParser(model="got-ocr2")
result = parser.parse("./lecture.pdf", output_dir="./output")

for page in result.pages:
    print(f"Page {page.page} ({page.source}): {page.text[:100]}...")
    for img in page.images:
        print(f"  Image: {img['id']} ({img['width']}x{img['height']})")
```

## Output format

```json
{
  "filename": "lecture.pdf",
  "pages": [
    {
      "page": 1,
      "text": "Convex Optimization\n\nConvex Sets...",
      "source": "text_layer",
      "images": []
    },
    {
      "page": 5,
      "text": "A set C is convex if...",
      "source": "text_layer",
      "images": [
        { "id": "p5_img0", "width": 640, "height": 480, "path": "output/images/p5_img0.png" }
      ]
    }
  ],
  "metadata": {
    "total_pages": 73,
    "ocr_pages": 0,
    "text_layer_pages": 73,
    "images_extracted": 15,
    "model": "got-ocr2",
    "force_ocr": false,
    "elapsed_ms": 320.5
  }
}
```

`source` is `"text_layer"` for pages where embedded text was used, or the model name (e.g., `"got-ocr2"`) for pages that went through OCR.

## Available models

| Model | Params | VRAM | Best for |
|-------|--------|------|----------|
| `got-ocr2` (default) | 580M | ~4GB | General OCR, typed + handwritten text, tables, formulas |
| `qwen-vl` | 7B | ~8GB | Messy handwriting, complex layouts (install with `--extra qwen`) |

## Adding a new model backend

Create a new file in `src/document_parser/models/` and use the `@register_engine` decorator:

```python
from document_parser.engine import OCREngine, register_engine

@register_engine("my-model")
class MyEngine(OCREngine):
    def load(self):
        # Load model weights
        ...

    def run(self, image):
        # Run OCR, return text string
        ...
```

Then import it in `src/document_parser/models/__init__.py` so the decorator runs on startup.

## Project structure

```
src/document_parser/
├── __init__.py        # Public API
├── engine.py          # OCREngine ABC, ModelRegistry, @register_engine
├── extractor.py       # PyMuPDF: text extraction, page rendering, image extraction
├── parser.py          # Smart routing orchestrator
├── models/
│   ├── got_ocr2.py    # GOT-OCR2 backend (default)
│   └── qwen_vl.py     # Qwen2.5-VL backend (optional)
├── server.py          # FastAPI server
└── cli.py             # Typer CLI
```
