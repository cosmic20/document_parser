import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, wsUrl } from "../api";
import type { Manifest, ManifestDoc } from "../api";

const stemOf = (file: string) => file.replace(/\.pdf$/i, "");

export default function ClassPage() {
  const { id } = useParams();
  const cid = id!;
  const [man, setMan] = useState<Manifest | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [prog, setProg] = useState<{ page: number; total: number } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = () => api.manifest(cid).then(setMan);
  useEffect(() => {
    load();
  }, [cid]);

  if (!man) return <p>Loading…</p>;

  const setDoc = (i: number, patch: Partial<ManifestDoc>) =>
    setMan({ ...man, documents: man.documents.map((d, j) => (j === i ? { ...d, ...patch } : d)) });

  // Reorder a row; this order drives both processing and Vaultify, so persist it immediately.
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= man.documents.length) return;
    const docs = man.documents.slice();
    [docs[i], docs[j]] = [docs[j], docs[i]];
    const next = { ...man, documents: docs };
    setMan(next);
    api.saveManifest(cid, next);
  };

  const upload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.length) {
      await api.upload(cid, e.target.files);
      load();
    }
  };

  const run = async () => {
    await api.saveManifest(cid, man);
    setLog([]);
    setRunning(true);
    const { job_id } = await api.process(cid);
    const ws = new WebSocket(wsUrl(`/api/jobs/${job_id}/events`));
    ws.onmessage = (m) => {
      const ev = JSON.parse(m.data);
      if (ev.type === "doc_start")
        setLog((s) => [...s, `▶ ${ev.title}  [${ev.engine}]  (${ev.index + 1}/${ev.total_docs})`]);
      else if (ev.type === "page") {
        setProg({ page: ev.page, total: ev.total });
        setLog((s) => [...s, `    p${ev.page}/${ev.total}  ${ev.source}  ${ev.chars}c  ${Math.round(ev.elapsed_ms)}ms`]);
      } else if (ev.type === "doc_done") setLog((s) => [...s, `✓ done — ${ev.pages} pages, ${ev.images} images`]);
      else if (ev.type === "doc_skipped") setLog((s) => [...s, `↷ skipped ${ev.file} (${ev.reason})`]);
      else if (ev.type === "error") setLog((s) => [...s, `✗ ${ev.message}`]);
      else if (ev.type === "job_done") {
        setRunning(false);
        setProg(null);
        load();
      }
    };
    ws.onerror = () => setRunning(false);
  };

  const anyProcessed = man.documents.some((d) => d.status !== "pending");

  return (
    <div>
      <Link to="/">← Classes</Link>
      <h1>{man.course}</h1>
      {man.source && (
        <p className="muted">
          ↪ registered source: <span className="mono">{man.source}</span> (read-only; output stays
          in the workspace)
        </p>
      )}

      <p className="muted">
        Order = teaching order. Use ↑/↓ to arrange lectures top-to-bottom; both processing and
        Vaultify follow this order, so you can name lectures by content instead of numbering them.
      </p>

      <table className="grid">
        <thead>
          <tr>
            <th>Order</th>
            <th>PDF</th>
            <th>Title</th>
            <th>Engine</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {man.documents.map((d, i) => (
            <tr key={d.file}>
              <td className="order-cell">
                <button className="mini" disabled={i === 0} onClick={() => move(i, -1)} title="Move up">
                  ↑
                </button>
                <button
                  className="mini"
                  disabled={i === man.documents.length - 1}
                  onClick={() => move(i, 1)}
                  title="Move down"
                >
                  ↓
                </button>
              </td>
              <td className="mono">{d.file}</td>
              <td>
                <input value={d.title} onChange={(e) => setDoc(i, { title: e.target.value })} />
              </td>
              <td>
                <select value={d.engine} onChange={(e) => setDoc(i, { engine: e.target.value })}>
                  {man.engines.map((en) => (
                    <option key={en}>{en}</option>
                  ))}
                </select>
              </td>
              <td>
                {d.status !== "pending" ? (
                  <Link to={`/class/${encodeURIComponent(cid)}/doc/${encodeURIComponent(stemOf(d.file))}`}>
                    <span className={`chip ${d.status}`}>{d.status}</span>
                  </Link>
                ) : (
                  <span className="chip pending">pending</span>
                )}
              </td>
            </tr>
          ))}
          {man.documents.length === 0 && (
            <tr>
              <td colSpan={5} className="muted">
                No PDFs yet — upload some below.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <div className="actions">
        {!man.source && (
          <>
            <input type="file" accept="application/pdf" multiple ref={fileRef} onChange={upload} hidden />
            <button onClick={() => fileRef.current?.click()}>＋ Upload PDFs</button>
          </>
        )}
        <button onClick={() => api.saveManifest(cid, man)}>Save manifest</button>
        <button className="primary" disabled={running || !man.documents.length} onClick={run}>
          {running ? "Processing…" : "Run processing"}
        </button>
        {anyProcessed && (
          <Link className="btn primary" to={`/class/${encodeURIComponent(cid)}/vaultify`}>
            ✨ Vaultify
          </Link>
        )}
      </div>

      {prog && (
        <div className="bar">
          <div className="bar-fill" style={{ width: `${(prog.page / (prog.total || 1)) * 100}%` }} />
        </div>
      )}
      {log.length > 0 && <pre className="log">{log.join("\n")}</pre>}
    </div>
  );
}
