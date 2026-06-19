"""Tests for the web app backend — FastAPI TestClient, offline (stub engine).

The workspace root is redirected to a temp dir per test, and processing uses a registered stub
OCR engine so no model weights are downloaded.
"""

from __future__ import annotations

import fitz
import pytest
from fastapi.testclient import TestClient

from document_parser import vault, webapp
from document_parser.engine import OCREngine, register_engine


@register_engine("stub-ocr")
class _StubOCR(OCREngine):
    def load(self) -> None:
        pass

    def run(self, image) -> str:
        return "stub ocr text"


def _pdf_bytes(text: str | None = None, pages: int = 1) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def client(tmp_path, monkeypatch):
    ws = tmp_path / "workspace"
    monkeypatch.setattr(vault, "load_config_workspace_path", lambda: ws)
    return TestClient(webapp.app)


def _create_class(client, name="ML101") -> str:
    r = client.post("/api/classes", json={"name": name})
    assert r.status_code == 200
    return r.json()["id"]


# ---------------------------------------------------------------- classes + upload


def test_create_and_list_class(client):
    cid = _create_class(client)
    classes = client.get("/api/classes").json()["classes"]
    assert [c["id"] for c in classes] == [cid]
    assert classes[0]["num_pdfs"] == 0


def test_upload_and_manifest_suggestions(client):
    cid = _create_class(client)
    files = [("files", ("scan0007.pdf", _pdf_bytes(text="typeset text " * 10), "application/pdf"))]
    assert client.post(f"/api/classes/{cid}/files", files=files).status_code == 200

    man = client.get(f"/api/classes/{cid}/manifest").json()
    assert man["course"] == cid
    doc = man["documents"][0]
    assert doc["file"] == "scan0007.pdf"
    assert doc["title"] == "Scan0007"  # normalized
    assert doc["engine"] == "marker"  # has a text layer → typeset suggestion
    assert doc["status"] == "pending"


def test_save_manifest_overrides(client):
    cid = _create_class(client)
    files = [("files", ("lec1.pdf", _pdf_bytes(text="hello world " * 5), "application/pdf"))]
    client.post(f"/api/classes/{cid}/files", files=files)

    body = {
        "course": cid,
        "default_engine": "stub-ocr",
        "documents": [{"file": "lec1.pdf", "title": "Lecture 1", "engine": "stub-ocr"}],
    }
    assert client.put(f"/api/classes/{cid}/manifest", json=body).status_code == 200
    man = client.get(f"/api/classes/{cid}/manifest").json()
    assert man["documents"][0]["title"] == "Lecture 1"
    assert man["documents"][0]["engine"] == "stub-ocr"


# ----------------------------------------------------------------- process + review


def test_process_streams_progress_and_produces_output(client):
    cid = _create_class(client)
    # No text layer → routes to OCR → stub engine (fast, offline).
    files = [("files", ("lec1.pdf", _pdf_bytes(text=None), "application/pdf"))]
    client.post(f"/api/classes/{cid}/files", files=files)

    job_id = client.post(f"/api/classes/{cid}/process", json={"engine": "stub-ocr"}).json()["job_id"]

    seen = []
    with client.websocket_connect(f"/api/jobs/{job_id}/events") as ws:
        while True:
            ev = ws.receive_json()
            seen.append(ev["type"])
            if ev["type"] == "job_done":
                assert ev["status"] == "done"
                break

    assert "doc_start" in seen and "page" in seen and "doc_done" in seen

    # The document is now processed and reviewable.
    docs = client.get(f"/api/classes/{cid}/documents").json()["documents"]
    assert docs[0]["status"] == "processed" and docs[0]["engine"] == "stub-ocr"

    data = client.get(f"/api/classes/{cid}/documents/lec1").json()
    assert data["metadata"]["model"] == "stub-ocr"
    assert data["pages"][0]["text"] == "stub ocr text"

    # Source page renders to PNG.
    png = client.get(f"/api/classes/{cid}/documents/lec1/page/1.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"


def test_process_unknown_engine_rejected(client):
    cid = _create_class(client)
    files = [("files", ("lec1.pdf", _pdf_bytes(text=None), "application/pdf"))]
    client.post(f"/api/classes/{cid}/files", files=files)
    r = client.post(f"/api/classes/{cid}/process", json={"engine": "nope"})
    assert r.status_code == 400


def test_register_external_keeps_source_clean(client, tmp_path):
    # An existing class folder elsewhere on disk (not in the workspace).
    ext = tmp_path / "Probability"
    ext.mkdir()
    (ext / "lec1.pdf").write_bytes(_pdf_bytes(text=None))

    summary = client.post("/api/classes/register", json={"path": str(ext)}).json()
    assert summary["source"] == str(ext)
    assert summary["num_pdfs"] == 1
    cid = summary["id"]

    man = client.get(f"/api/classes/{cid}/manifest").json()
    assert man["source"] == str(ext)

    # Upload is rejected for a registered class (source is managed externally).
    up = client.post(
        f"/api/classes/{cid}/files",
        files=[("files", ("x.pdf", _pdf_bytes(), "application/pdf"))],
    )
    assert up.status_code == 400

    # Process → output lands in the WORKSPACE work folder, leaving the source pristine.
    job = client.post(f"/api/classes/{cid}/process", json={"engine": "stub-ocr"}).json()["job_id"]
    with client.websocket_connect(f"/api/jobs/{job}/events") as ws:
        while ws.receive_json()["type"] != "job_done":
            pass

    work = tmp_path / "workspace" / "Probability"
    assert (work / "_parsed" / "lec1" / "lec1.json").exists()
    assert (work / "batch.toml").exists()
    assert not (ext / "_parsed").exists()  # source untouched
    assert not (ext / "batch.toml").exists()

    data = client.get(f"/api/classes/{cid}/documents/lec1").json()
    assert data["metadata"]["model"] == "stub-ocr"
