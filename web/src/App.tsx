import { Link, Route, Routes } from "react-router-dom";
import ClassPage from "./pages/ClassPage";
import Library from "./pages/Library";
import Review from "./pages/Review";
import Vaultify from "./pages/Vaultify";

export default function App() {
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">📄 docparse</div>
        <nav>
          <Link to="/">Library</Link>
        </nav>
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
