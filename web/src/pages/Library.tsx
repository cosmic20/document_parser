import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { ClassSummary } from "../api";

export default function Library() {
  const [classes, setClasses] = useState<ClassSummary[]>([]);
  const [workspace, setWorkspace] = useState("");
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [err, setErr] = useState("");

  const load = () =>
    api
      .listClasses()
      .then((r) => {
        setClasses(r.classes);
        setWorkspace(r.workspace);
      })
      .catch((e) => setErr(e.message));

  useEffect(() => {
    load();
  }, []);

  const create = async () => {
    if (!name.trim()) return;
    try {
      await api.createClass(name.trim());
      setName("");
      setErr("");
      load();
    } catch (e: any) {
      setErr(e.message);
    }
  };

  const register = async (folder?: string) => {
    const p = (folder ?? path).trim();
    if (!p) return;
    try {
      await api.registerClass(p);
      setPath("");
      setErr("");
      load();
    } catch (e: any) {
      setErr(e.message);
    }
  };

  const browse = async () => {
    try {
      const r = await api.pickFolder(); // native Finder dialog (local backend)
      if (r.path) await register(r.path); // chosen ⇒ add it straight away
    } catch (e: any) {
      setErr(e.message);
    }
  };

  return (
    <div>
      <h1>Classes</h1>
      <p className="muted">Workspace: {workspace}</p>
      {err && <div className="error">{err}</div>}

      <div className="cards">
        {classes.map((c) => (
          <Link key={c.id} to={`/class/${encodeURIComponent(c.id)}`} className="card">
            <div className="card-title">{c.name}</div>
            <div className="muted">
              {c.num_pdfs} PDFs{c.source ? " · ↪ external" : ""}
            </div>
            <div className="chips">
              <span className="chip pending">{c.status.pending || 0} pending</span>
              <span className="chip processed">{c.status.processed || 0} processed</span>
              <span className="chip integrated">{c.status.integrated || 0} integrated</span>
            </div>
          </Link>
        ))}
        {classes.length === 0 && <p className="muted">No classes yet — create one below.</p>}
      </div>

      <div className="row">
        <div className="panel">
          <h3>New class — upload PDFs</h3>
          <p className="muted">Make an empty class, then add PDFs from your computer.</p>
          <input
            placeholder="e.g. 21-325 Probability"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && create()}
          />
          <button className="primary" onClick={create}>
            Create &amp; upload
          </button>
        </div>
        <div className="panel">
          <h3>Use a folder I already have</h3>
          <p className="muted">Point at an existing folder of PDFs — read in place, nothing moved.</p>
          <button className="primary" onClick={browse}>
            📁 Choose folder…
          </button>
          <div className="muted" style={{ margin: "12px 0 6px" }}>or paste a path:</div>
          <div className="path-row">
            <input
              placeholder="/path/to/class-folder"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && register()}
            />
            <button onClick={() => register()}>Add</button>
          </div>
        </div>
      </div>
    </div>
  );
}
