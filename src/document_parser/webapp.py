"""Local web app backend — a FastAPI layer over the batch pipeline.

Single-user, local-first: class folders live under a workspace root; this app lets the browser UI
create classes, upload PDFs, edit the engine/title manifest, run batch processing with live
progress (WebSocket), and review parsed output. The vault-build step is driven separately through
an embedded Claude Code terminal (see ``/api/classes/{id}/terminal``). Launch via ``docparse web``.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
from dataclasses import asdict
from pathlib import Path

import fitz  # PyMuPDF
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from document_parser import batch, jobs, terminals, vault
from document_parser.engine import ModelRegistry
from document_parser.parser import DEFAULT_MODEL

# Register the model backends.
import document_parser.models  # noqa: F401

DEFAULT_WORKSPACE = Path.home() / "Documents" / "docparse-classes"
REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_DIST = REPO_ROOT / "web" / "dist"

app = FastAPI(title="Document Parser — Web", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------------- helpers


def workspace_root() -> Path:
    root = vault.load_config_workspace_path() or DEFAULT_WORKSPACE
    root.mkdir(parents=True, exist_ok=True)
    return root


def _class_dir(class_id: str) -> Path:
    if "/" in class_id or ".." in class_id:
        raise HTTPException(400, "invalid class id")
    d = workspace_root() / class_id
    if not d.is_dir():
        raise HTTPException(404, f"class '{class_id}' not found")
    return d


def _class_summary(d: Path) -> dict:
    idx = batch.load_index(d)
    src = batch.source_dir(d)
    counts = {"pending": 0, "processed": 0, "integrated": 0}
    pdfs = batch.list_pdfs(src)
    for pdf in pdfs:
        e = idx.get(pdf.name)
        st = e.status if e else "pending"
        counts[st] = counts.get(st, 0) + 1
    return {
        "id": d.name,
        "name": d.name,
        "num_pdfs": len(pdfs),
        "status": counts,
        "source": str(src) if src != d else None,  # set ⇒ registered (external) class
    }


def _source_pdf(d: Path, stem: str) -> Path:
    for f in batch.list_pdfs(batch.source_dir(d)):
        if f.stem == stem:
            return f
    raise HTTPException(404, "source pdf not found")


# -------------------------------------------------------------------- request models


class ClassIn(BaseModel):
    name: str


class RegisterIn(BaseModel):
    path: str


class DocIn(BaseModel):
    file: str
    title: str
    engine: str


class ManifestIn(BaseModel):
    course: str
    default_engine: str
    documents: list[DocIn]


class ProcessIn(BaseModel):
    engine: str | None = None
    force: bool = False


class ConfigIn(BaseModel):
    workspace: str | None = None
    vault: str | None = None


# --------------------------------------------------------------------------- config


@app.get("/api/engines")
def engines() -> dict:
    return {"engines": ModelRegistry.available(), "default": DEFAULT_MODEL}


@app.get("/api/config")
def get_config() -> dict:
    vp = vault.load_config_vault_path()
    return {"workspace": str(workspace_root()), "vault": str(vp) if vp else None}


@app.put("/api/config")
def put_config(body: ConfigIn) -> dict:
    if body.workspace:
        vault.save_config_workspace_path(Path(body.workspace))
    if body.vault:
        vault.save_config_vault_path(Path(body.vault))
    return get_config()


# -------------------------------------------------------------------------- classes


@app.get("/api/classes")
def list_classes() -> dict:
    root = workspace_root()
    classes = [_class_summary(d) for d in sorted(root.iterdir()) if d.is_dir()]
    return {"classes": classes, "workspace": str(root)}


@app.post("/api/classes")
def create_class(body: ClassIn) -> dict:
    name = body.name.strip()
    if not name or "/" in name or ".." in name:
        raise HTTPException(400, "invalid class name")
    d = workspace_root() / name
    d.mkdir(parents=True, exist_ok=True)
    return _class_summary(d)


@app.post("/api/classes/register")
def register_class(body: RegisterIn) -> dict:
    ext = Path(body.path).expanduser()
    if not ext.is_dir():
        raise HTTPException(400, "path is not a directory")
    work = workspace_root() / ext.name
    if work.exists():
        raise HTTPException(409, f"a class named '{ext.name}' already exists")
    work.mkdir(parents=True)
    # Register: PDFs are read from the external source; batch.toml + _parsed output stay in the
    # workspace work folder, leaving the source folder pristine.
    batch.write_manifest(work, batch.scaffold_manifest(work, source=ext))
    return _class_summary(work)


@app.post("/api/pick-folder")
async def pick_folder() -> dict:
    """Open a native macOS folder chooser and return the chosen absolute path (or null)."""
    import shutil
    import subprocess

    if shutil.which("osascript") is None:
        raise HTTPException(400, "native folder picker is only available on macOS")

    def choose() -> str | None:
        try:
            r = subprocess.run(
                ["osascript", "-e", 'POSIX path of (choose folder with prompt "Choose a class folder")'],
                capture_output=True,
                text=True,
                timeout=300,
            )
        except Exception:
            return None
        out = r.stdout.strip()
        return out if r.returncode == 0 and out else None  # non-zero ⇒ user cancelled

    return {"path": await asyncio.to_thread(choose)}


@app.post("/api/classes/{class_id}/files")
async def upload_files(class_id: str, files: list[UploadFile] = File(...)) -> dict:
    d = _class_dir(class_id)
    if batch.source_dir(d) != d:
        raise HTTPException(400, "this class is registered to an external folder — add PDFs there")
    saved = []
    for f in files:
        name = Path(f.filename or "upload.pdf").name
        (d / name).write_bytes(await f.read())
        saved.append(name)
    return {"saved": saved, "class": _class_summary(d)}


# ------------------------------------------------------------------------- manifest


@app.get("/api/classes/{class_id}/manifest")
def get_manifest(class_id: str) -> dict:
    d = _class_dir(class_id)
    man = batch.load_manifest(d) or batch.scaffold_manifest(d)
    idx = batch.load_index(d)
    docs = []
    for doc in man.documents:
        e = idx.get(doc.file)
        docs.append(
            {
                "file": doc.file,
                "title": doc.title,
                "engine": doc.engine or man.default_engine,
                "status": e.status if e else "pending",
                "pages": e.pages if e else 0,
            }
        )
    return {
        "course": man.course,
        "default_engine": man.default_engine,
        "documents": docs,
        "engines": ModelRegistry.available(),
        "source": man.source,
    }


@app.put("/api/classes/{class_id}/manifest")
def put_manifest(class_id: str, body: ManifestIn) -> dict:
    d = _class_dir(class_id)
    existing = batch.load_manifest(d)
    man = batch.BatchManifest(
        course=body.course,
        default_engine=body.default_engine,
        documents=[batch.DocEntry(file=x.file, title=x.title, engine=x.engine) for x in body.documents],
        source=existing.source if existing else None,  # preserve the registered source
    )
    batch.write_manifest(d, man)
    return {"ok": True}


# ------------------------------------------------------------------------ processing


@app.post("/api/classes/{class_id}/process")
def process(class_id: str, body: ProcessIn) -> dict:
    d = _class_dir(class_id)
    if body.engine and body.engine not in ModelRegistry.available():
        raise HTTPException(400, f"unknown engine '{body.engine}'")
    job = jobs.start_processing(class_id, d, body.engine, body.force)
    return {"job_id": job.id}


@app.websocket("/api/jobs/{job_id}/events")
async def job_events(ws: WebSocket, job_id: str) -> None:
    await ws.accept()
    job = jobs.get_job(job_id)
    if job is None:
        await ws.send_json({"type": "error", "message": "unknown job"})
        await ws.close()
        return
    while True:
        try:
            ev = await asyncio.to_thread(job.queue.get, True, 0.5)
        except queue.Empty:
            continue
        try:
            await ws.send_json(ev)
        except Exception:
            break
        if ev.get("type") == "job_done":
            break
    await ws.close()


# ------------------------------------------------------------------------- documents


@app.get("/api/classes/{class_id}/documents")
def documents(class_id: str) -> dict:
    d = _class_dir(class_id)
    return {"documents": [asdict(e) for e in batch.load_index(d).values()]}


@app.get("/api/classes/{class_id}/documents/{stem}")
def document_json(class_id: str, stem: str) -> dict:
    d = _class_dir(class_id)
    jp = d / batch.PARSED_DIRNAME / stem / f"{stem}.json"
    if not jp.exists():
        raise HTTPException(404, "document not processed yet")
    return json.loads(jp.read_text())


@app.get("/api/classes/{class_id}/documents/{stem}/page/{page}.png")
def source_page(class_id: str, stem: str, page: int) -> Response:
    d = _class_dir(class_id)
    src = _source_pdf(d, stem)
    doc = fitz.open(str(src))
    try:
        if page < 1 or page > doc.page_count:
            raise HTTPException(404, "page out of range")
        pix = doc[page - 1].get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72))
        png = pix.tobytes("png")
    finally:
        doc.close()
    return Response(content=png, media_type="image/png")


@app.get("/api/classes/{class_id}/documents/{stem}/image/{img}.png")
def document_image(class_id: str, stem: str, img: str) -> FileResponse:
    d = _class_dir(class_id)
    p = d / batch.PARSED_DIRNAME / stem / "images" / f"{img}.png"
    if not p.exists():
        raise HTTPException(404, "image not found")
    return FileResponse(p)


# ------------------------------------------------------------------------- vaultify


@app.websocket("/api/classes/{class_id}/terminal")
async def terminal(ws: WebSocket, class_id: str) -> None:
    """Attach the browser terminal to this class's persistent Claude Code (vault-build) session.

    The session lives in ``terminals.manager`` independent of this socket: disconnecting *detaches*
    (claude keeps running, so document processing can run concurrently) and reconnecting
    *re-attaches* and replays recent output. claude runs in the repo root so the skills resolve.
    """
    import shutil

    await ws.accept()
    try:
        d = _class_dir(class_id)
    except HTTPException as e:
        await ws.send_text(f"{e.detail}\r\n")
        await ws.close()
        return

    session = terminals.manager.get(class_id)
    if session is None:
        if shutil.which("claude") is None:
            await ws.send_text("Claude Code CLI ('claude') not found on PATH.\r\n")
            await ws.close()
            return
        vault_path = vault.load_config_vault_path() or (Path.home() / "CMU-Vault")
        prompt = (
            f"Use the vault-build skill to integrate the processed documents in '{d}' into the "
            f"Obsidian vault at '{vault_path}'. Read that class folder's _parsed/batch_index.json "
            f"and only integrate documents whose status is 'processed'."
        )
        # vault-build is structured translation/organization work — Sonnet handles it well and
        # burns far less of the usage limit than Opus. Override with DOCPARSE_AGENT_MODEL="opus"
        # (or "" to use the CLI default).
        model = os.environ.get("DOCPARSE_AGENT_MODEL", "sonnet")
        argv = ["claude", "--model", model, prompt] if model else ["claude", prompt]
        session = terminals.manager.ensure(class_id, REPO_ROOT, argv)

    if session.buffer:  # replay recent scrollback to the (re)attaching terminal
        await ws.send_bytes(bytes(session.buffer))
    session.ws = ws

    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                terminals.manager.write(session, msg["bytes"])  # keystrokes
            elif msg.get("text") is not None:
                try:
                    ctrl = json.loads(msg["text"])
                except json.JSONDecodeError:
                    terminals.manager.write(session, msg["text"].encode())
                    continue
                if "resize" in ctrl:  # {"resize": {"rows": R, "cols": C}}
                    terminals.manager.resize(
                        session, int(ctrl["resize"]["rows"]), int(ctrl["resize"]["cols"])
                    )
    except WebSocketDisconnect:
        pass
    finally:
        if session.ws is ws:  # detach but leave claude running
            session.ws = None
        try:
            await ws.close()
        except Exception:
            pass


@app.post("/api/classes/{class_id}/terminal/stop")
def stop_terminal(class_id: str) -> dict:
    terminals.manager.stop(class_id)
    return {"ok": True}


@app.get("/api/activity")
def activity() -> dict:
    """What's currently running — for the sidebar indicator (processing jobs + live terminals)."""
    return {"processing": jobs.list_active(), "terminals": terminals.manager.active_class_ids()}


@app.on_event("shutdown")
def _shutdown() -> None:
    terminals.manager.shutdown()


# ----------------------------------------------------------- static SPA (built UI)
# Mounted last so API routes take precedence; only present after `npm run build`.
if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="web")
