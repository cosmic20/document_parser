"""CLI interface — docparse command."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import typer

from document_parser.engine import ModelRegistry, ParseResult
from document_parser.parser import DEFAULT_MODEL, DocumentParser

# Ensure backends are registered
import document_parser.models  # noqa: F401

app = typer.Typer(
    name="docparse",
    help="Handwriting-aware PDF/image OCR with pluggable model backends.",
    no_args_is_help=True,
)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )


@app.command()
def parse(
    source: Path = typer.Argument(..., help="Path to a PDF or image file", exists=True),
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m", help="OCR model backend"),
    output: Path = typer.Option(None, "--output", "-o", help="Output directory"),
    format: str = typer.Option("json", "--format", "-f", help="Output format: json or markdown"),
    force_ocr: bool = typer.Option(False, "--force-ocr", help="Force OCR on all pages"),
    use_llm: bool = typer.Option(
        False, "--use-llm", help="Enable LLM augmentation (document backends like marker)"
    ),
    dpi: int = typer.Option(200, "--dpi", help="Render DPI for page images"),
    text_threshold: int = typer.Option(
        10, "--text-threshold", help="Min chars to consider text layer usable"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),
):
    """Parse a PDF or image file into structured text + images."""
    _setup_logging(verbose)

    # Validate model
    available = ModelRegistry.available()
    if model not in available:
        typer.echo(f"Error: Unknown model '{model}'. Available: {', '.join(available)}")
        raise typer.Exit(1)

    # Default output dir
    if output is None:
        output = source.parent / f"{source.stem}_parsed"

    output.mkdir(parents=True, exist_ok=True)

    typer.echo(f"Parsing: {source.name}")
    typer.echo(f"Model:   {model} (force_ocr={force_ocr})")
    typer.echo(f"Output:  {output}")
    typer.echo()

    parser = DocumentParser(
        model=model,
        dpi=dpi,
        text_threshold=text_threshold,
        force_ocr=force_ocr,
        use_llm=use_llm,
    )

    result = parser.parse(source=source, output_dir=output)

    # Write output
    if format == "json":
        out_file = output / f"{source.stem}.json"
        with open(out_file, "w") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
        typer.echo(f"Wrote JSON: {out_file}")

    elif format == "markdown":
        out_file = output / f"{source.stem}.md"
        with open(out_file, "w") as f:
            f.write(_to_markdown(result))
        typer.echo(f"Wrote Markdown: {out_file}")

    else:
        typer.echo(f"Error: Unknown format '{format}'. Use 'json' or 'markdown'.")
        raise typer.Exit(1)

    # Summary
    meta = result.metadata
    typer.echo()
    typer.echo(
        f"Done: {meta['total_pages']} pages "
        f"({meta['text_layer_pages']} text layer, {meta['ocr_pages']} OCR), "
        f"{meta['images_extracted']} images, "
        f"{meta['elapsed_ms']:.0f}ms"
    )


@app.command()
def models():
    """List available OCR model backends."""
    available = ModelRegistry.available()
    typer.echo(f"Available models ({len(available)}):")
    for name in available:
        default_marker = " (default)" if name == DEFAULT_MODEL else ""
        typer.echo(f"  - {name}{default_marker}")


def _to_markdown(result: ParseResult) -> str:
    """Convert a ParseResult to a simple markdown document."""
    lines = [
        f"# {result.filename}",
        "",
    ]

    for page in result.pages:
        lines.append(f"## Page {page.page}")
        lines.append("")
        lines.append(f"*Source: {page.source}*")
        lines.append("")
        lines.append(page.text)
        lines.append("")

        for img in page.images:
            img_path = img.get("path", img["id"])
            lines.append(f"![{img['id']}]({img_path})")
            lines.append("")

    return "\n".join(lines)
