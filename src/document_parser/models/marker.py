"""Marker backend — document-level pipeline via datalab-to/marker.

Unlike the image→text OCR engines, marker owns the whole document: layout
analysis, reading order, table/equation recognition, and image extraction. We run
its JSON renderer and map each marker page to a PageResult, preserving structure in
the ``blocks`` field (resolved HTML per block: tables, equations, headings).

Install with: uv sync --extra marker
"""

from __future__ import annotations

import base64
import binascii
import html as htmllib
import io
import logging
import os
import re
import tempfile
from pathlib import Path

from PIL import Image

from document_parser.engine import DocumentEngine, PageResult, register_engine

logger = logging.getLogger("document_parser")

# Default Claude model used when use_llm is enabled. Bump as newer ids ship.
DEFAULT_CLAUDE_MODEL = "claude-3-7-sonnet-20250219"

_TAG_RE = re.compile(r"<[^>]+>")
# marker references child blocks inside a parent's html via <content-ref src='...'>
_CONTENT_REF_RE = re.compile(
    r"<content-ref\s+src=['\"]([^'\"]+)['\"]\s*>\s*</content-ref>", re.IGNORECASE
)
# block tags whose boundaries should become line breaks when flattening to text
_BREAK_RE = re.compile(r"(?i)<\s*(br|/p|/div|/h[1-6]|/li|/tr|/table)\s*/?>")
# running heads / page numbers — dropped from flattened text
_NOISE_BLOCK_TYPES = {"PageHeader", "PageFooter"}


@register_engine("marker")
class MarkerEngine(DocumentEngine):
    """Document-level backend using marker (Surya pipeline)."""

    def __init__(self):
        self.models = None
        self.use_llm = False
        self.claude_model = DEFAULT_CLAUDE_MODEL

    def load(self) -> None:
        from document_parser.device import get_device

        # marker reads the device from TORCH_DEVICE; it must be set before import.
        # setdefault lets a user pin TORCH_DEVICE=cpu (marker's MPS path is flaky).
        os.environ.setdefault("TORCH_DEVICE", get_device())

        try:
            from marker.models import create_model_dict
        except ImportError as e:
            raise ImportError(
                "Marker backend requires extra dependencies. "
                "Install with: uv sync --extra marker"
            ) from e

        logger.info(
            f"Loading marker models (TORCH_DEVICE={os.environ.get('TORCH_DEVICE')})..."
        )
        self.models = create_model_dict()
        logger.info("Marker models loaded.")

    def run_document(
        self, source: str | Path | bytes, images_dir: Path | None
    ) -> list[PageResult]:
        self.ensure_loaded()

        # marker takes a filesystem path; spill bytes to a temp file if needed.
        tmp_path = None
        if isinstance(source, (bytes, bytearray)):
            fd, tmp_path = tempfile.mkstemp(suffix=".pdf", prefix="docparse_marker_")
            with os.fdopen(fd, "wb") as f:
                f.write(source)
            path = tmp_path
        else:
            path = str(source)

        try:
            rendered = self._convert(path)
        finally:
            if tmp_path is not None:
                os.unlink(tmp_path)

        doc = rendered.model_dump() if hasattr(rendered, "model_dump") else rendered
        page_nodes = doc.get("children") or []

        results: list[PageResult] = []
        for page_num, page_node in enumerate(page_nodes, start=1):
            index: dict[str, dict] = {}
            _index_nodes(page_node, index)

            blocks = []
            for child in page_node.get("children") or []:
                blocks.append(
                    {
                        "id": child.get("id"),
                        "block_type": child.get("block_type"),
                        "bbox": child.get("bbox"),
                        "html": _resolve_html(child, index),
                    }
                )

            text = self._blocks_to_text(blocks)
            images = self._save_page_images(page_node, page_num, images_dir)

            results.append(
                PageResult(
                    page=page_num,
                    text=text,
                    source=self.name,
                    images=images,
                    blocks=blocks,
                )
            )

        return results

    def _convert(self, path: str):
        from marker.config.parser import ConfigParser
        from marker.converters.pdf import PdfConverter

        config: dict = {"output_format": "json"}
        if self.use_llm:
            config.update(
                {
                    "use_llm": True,
                    "llm_service": "marker.services.claude.ClaudeService",
                    "claude_model_name": self.claude_model,
                }
            )
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if api_key:
                config["claude_api_key"] = api_key

        cp = ConfigParser(config)
        converter = PdfConverter(
            config=cp.generate_config_dict(),
            artifact_dict=self.models,
            processor_list=cp.get_processors(),
            renderer=cp.get_renderer(),  # REQUIRED — JSON output is ignored without it
            llm_service=cp.get_llm_service(),
        )
        return converter(path)

    def _blocks_to_text(self, blocks: list[dict]) -> str:
        parts = []
        for block in blocks:
            if block.get("block_type") in _NOISE_BLOCK_TYPES:
                continue
            parts.append(_html_to_text(block.get("html") or ""))
        return "\n\n".join(p for p in parts if p).strip()

    def _save_page_images(
        self, page_node: dict, page_num: int, images_dir: Path | None
    ) -> list[dict]:
        refs: list[dict] = []
        idx = 0
        for node in _iter_nodes(page_node):
            for _block_id, b64 in (node.get("images") or {}).items():
                try:
                    data = base64.b64decode(b64)
                    img = Image.open(io.BytesIO(data)).convert("RGB")
                except (binascii.Error, ValueError, OSError):
                    continue
                ref = {"id": f"p{page_num}_img{idx}", "width": img.width, "height": img.height}
                if images_dir is not None:
                    img_path = images_dir / f"p{page_num}_img{idx}.png"
                    img.save(img_path, "PNG")
                    ref["path"] = str(img_path)
                refs.append(ref)
                idx += 1
        return refs


def _iter_nodes(node: dict):
    """Yield a block node and all its descendants."""
    yield node
    for child in node.get("children") or []:
        yield from _iter_nodes(child)


def _index_nodes(node: dict, index: dict[str, dict]) -> None:
    """Build an id → node index for resolving <content-ref> children."""
    node_id = node.get("id")
    if node_id is not None:
        index[node_id] = node
    for child in node.get("children") or []:
        _index_nodes(child, index)


def _resolve_html(node: dict, index: dict[str, dict]) -> str:
    """Inline child <content-ref> placeholders into a block's html, recursively."""
    html = node.get("html") or ""

    def repl(match: re.Match) -> str:
        child = index.get(match.group(1))
        return _resolve_html(child, index) if child else ""

    return _CONTENT_REF_RE.sub(repl, html)


def _html_to_text(html: str) -> str:
    """Flatten resolved block html to plain text, keeping rough line structure."""
    text = _BREAK_RE.sub("\n", html)
    text = _TAG_RE.sub("", text)
    text = htmllib.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
