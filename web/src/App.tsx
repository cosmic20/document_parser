import { useEffect, useState } from "react";
import { Link, Route, Routes } from "react-router-dom";
import { api } from "./api";
import ClassPage from "./pages/ClassPage";
import Library from "./pages/Library";
import Review from "./pages/Review";
import Vaultify from "./pages/Vaultify";

function Activity() {
  const [act, setAct] = useState<{ processing: any[]; terminals: string[] }>({
    processing: [],
    terminals: [],
  });
  useEffect(() => {
    let on = true;
    const tick = () => api.activity().then((a) => on && setAct(a)).catch(() => {});
    tick();
    const id = setInterval(tick, 3000);
    return () => {
      on = false;
      clearInterval(id);
    };
  }, []);
  if (!act.processing.length && !act.terminals.length) return null;
  return (
    <div className="activity">
      <div className="activity-title">Running</div>
      {act.processing.map((p) => (
        <Link key={p.id} className="activity-item" to={`/class/${encodeURIComponent(p.class_id)}`}>
          ⚙ {p.class_id}
        </Link>
      ))}
      {act.terminals.map((cid) => (
        <Link key={cid} className="activity-item" to={`/class/${encodeURIComponent(cid)}/vaultify`}>
          ✨ {cid}
        </Link>
      ))}
    </div>
  );
}

export default function App() {
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">📄 docparse</div>
        <nav>
          <Link to="/">Library</Link>
        </nav>
        <Activity />
        <div className="sidebar-foot">Local · concept-first vault</div>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<Library />} />
          <Route path="/class/:id" element={<ClassPage />} />
          <Route path="/class/:id/doc/:stem" element={<Review />} />
          <Route path="/class/:id/vaultify" element={<Vaultify />} />
        </Routes>
      </main>
    </div>
  );
}
