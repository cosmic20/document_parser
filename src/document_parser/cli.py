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


batch_app = typer.Typer(name="batch", help="Process folders of class PDFs into JSON + an index.")
app.add_typer(batch_app)


@batch_app.command("init")
def batch_init(
    folders: list[Path] = typer.Argument(..., help="Class folder(s) to scaffold", exists=True),
):
    """Scaffold a batch.toml in each class folder (engine suggestions + normalized titles)."""
    from document_parser import batch as batch_mod

    for folder in folders:
        manifest = batch_mod.scaffold_manifest(folder)
        path = batch_mod.write_manifest(folder, manifest)
        typer.echo(f"Wrote {path}  (course='{manifest.course}', {len(manifest.documents)} docs)")
        for d in manifest.documents:
            typer.echo(f"  - {d.file}  →  '{d.title}'  [{d.engine}]")


@batch_app.command("run")
def batch_run(
    folders: list[Path] = typer.Argument(..., help="Class folder(s) to process", exists=True),
    engine: str = typer.Option(None, "--engine", "-e", help="Override engine for all documents"),
    force: bool = typer.Option(False, "--force", help="Reprocess already-processed documents"),
    dpi: int = typer.Option(200, "--dpi", help="Render DPI for page images"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),
):
    """Process pending PDFs in each class folder, writing _parsed/ JSON + batch_index.json."""
    from document_parser import batch as batch_mod

    _setup_logging(verbose)
    if engine and engine not in ModelRegistry.available():
        typer.echo(f"Error: Unknown engine '{engine}'. Available: {', '.join(ModelRegistry.available())}")
        raise typer.Exit(1)

    for folder in folders:
        typer.echo(f"Class: {folder.name}")
        entries = batch_mod.run_folder(folder, engine_override=engine, force=force, dpi=dpi)
        done = sum(e.status in ("processed", "integrated") for e in entries.values())
        typer.echo(f"  {done}/{len(entries)} documents processed → {batch_mod.index_path(folder)}")


@batch_app.command("status")
def batch_status(
    folder: Path = typer.Argument(..., help="Class folder to inspect", exists=True),
):
    """Print the batch index (document → engine → status) for a class folder."""
    from document_parser import batch as batch_mod

    entries = batch_mod.load_index(folder)
    if not entries:
        typer.echo(f"No batch index in {folder} (run 'docparse batch run' first).")
        raise typer.Exit()

    width = max(len(e.title) for e in entries.values())
    typer.echo(f"{'TITLE':<{width}}  {'ENGINE':<11}  {'STATUS':<10}  PAGES")
    for e in entries.values():
        typer.echo(f"{e.title:<{width}}  {e.engine:<11}  {e.status:<10}  {e.pages}")


vault_app = typer.Typer(name="vault", help="Maintain the concept index for the Obsidian vault.")
app.add_typer(vault_app)


@vault_app.command("index")
def vault_index(
    vault: Path = typer.Option(
        None, "--vault", help="Vault path (remembered in ~/.docparse.toml)", exists=True
    ),
):
    """Scan the vault into .vault-index.json (concepts + topic-dependency graph)."""
    from document_parser import vault as vault_mod

    path = vault or vault_mod.load_config_vault_path()
    if path is None:
        typer.echo("Error: no vault path. Pass --vault <path> once; it is then remembered.")
        raise typer.Exit(1)
    if vault is not None:
        vault_mod.save_config_vault_path(vault)

    out, index = vault_mod.write_index(path)
    topics = sorted({n["topic"] for n in index["notes"] if n["topic"]})
    typer.echo(f"Indexed {len(index['notes'])} notes across {len(topics)} topics → {out}")
    typer.echo(f"Topic dependencies: {sum(len(v) for v in index['topic_edges'].values())} edges")


@app.command()
def web(
    port: int = typer.Option(8765, "--port", help="Port to serve on"),
    no_open: bool = typer.Option(False, "--no-open", help="Don't open the browser"),
):
    """Launch the local web app (processing UI + Vaultify)."""
    import threading
    import webbrowser

    import uvicorn

    from document_parser.webapp import WEB_DIST

    if not WEB_DIST.is_dir():
        typer.echo(
            "Note: the web UI isn't built yet — only the API will serve.\n"
            "      Build it with:  cd web && npm install && npm run build\n"
            "      (or run the dev server separately:  cd web && npm run dev)\n"
        )

    url = f"http://localhost:{port}"
    if not no_open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    typer.echo(f"Serving docparse web at {url}  (Ctrl-C to stop)")
    uvicorn.run("document_parser.webapp:app", host="127.0.0.1", port=port)


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
