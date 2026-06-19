// Thin fetch client for the docparse web backend. All paths are relative so the same code works
// behind the Vite dev proxy and when served by FastAPI in production.

export interface ClassSummary {
  id: string;
  name: string;
  num_pdfs: number;
  status: Record<string, number>;
  source?: string | null; // set ⇒ registered (external source folder)
}

export interface ManifestDoc {
  file: string;
  title: string;
  engine: string;
  status: string;
  pages: number;
}

export interface Manifest {
  course: string;
  default_engine: string;
  documents: ManifestDoc[];
  engines: string[];
  source?: string | null; // set ⇒ registered (external source folder)
}

export interface DocRow {
  path: string;
  course: string;
  title: string;
  engine: string;
  json_path: string | null;
  pages: number;
  images: number;
  status: string;
  elapsed_ms: number;
}

async function j<T = any>(url: string, opts?: RequestInit): Promise<T> {
  const r = await fetch(url, opts);
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    throw new Error(detail.detail || r.statusText);
  }
  return r.json();
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

const enc = encodeURIComponent;

export const api = {
  listClasses: () => j<{ classes: ClassSummary[]; workspace: string }>("/api/classes"),
  createClass: (name: string) => j("/api/classes", json({ name })),
  registerClass: (path: string) => j("/api/classes/register", json({ path })),
  upload: (id: string, files: FileList) => {
    const fd = new FormData();
    Array.from(files).forEach((f) => fd.append("files", f));
    return j(`/api/classes/${enc(id)}/files`, { method: "POST", body: fd });
  },
  manifest: (id: string) => j<Manifest>(`/api/classes/${enc(id)}/manifest`),
  saveManifest: (id: string, m: Manifest) =>
    j(`/api/classes/${enc(id)}/manifest`, { ...json(m), method: "PUT" }),
  process: (id: string, engine?: string, force?: boolean) =>
    j<{ job_id: string }>(`/api/classes/${enc(id)}/process`, json({ engine: engine || null, force: !!force })),
  documents: (id: string) => j<{ documents: DocRow[] }>(`/api/classes/${enc(id)}/documents`),
  documentJson: (id: string, stem: string) => j(`/api/classes/${enc(id)}/documents/${enc(stem)}`),
  config: () => j<{ workspace: string; vault: string | null }>("/api/config"),
  pickFolder: () => j<{ path: string | null }>("/api/pick-folder", { method: "POST" }),
  activity: () =>
    j<{ processing: { id: string; class_id: string; status: string }[]; terminals: string[] }>(
      "/api/activity",
    ),
  stopTerminal: (id: string) => j(`/api/classes/${enc(id)}/terminal/stop`, { method: "POST" }),
};

export const pageImg = (id: string, stem: string, page: number) =>
  `/api/classes/${enc(id)}/documents/${enc(stem)}/page/${page}.png`;
export const docImg = (id: string, stem: string, img: string) =>
  `/api/classes/${enc(id)}/documents/${enc(stem)}/image/${img}.png`;

export function wsUrl(path: string): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}${path}`;
}
