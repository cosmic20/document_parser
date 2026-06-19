import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, docImg, pageImg } from "../api";

export default function Review() {
  const { id, stem } = useParams();
  const cid = id!;
  const st = stem!;
  const [data, setData] = useState<any>(null);
  const [page, setPage] = useState(1);

  useEffect(() => {
    api.documentJson(cid, st).then(setData);
  }, [cid, st]);

  if (!data) return <p>Loading…</p>;
  const p = data.pages.find((x: any) => x.page === page) || data.pages[0];

  return (
    <div>
      <Link to={`/class/${encodeURIComponent(cid)}`}>← {data.filename}</Link>
      <div className="pager">
        {data.pages.map((x: any) => (
          <button key={x.page} className={x.page === page ? "active" : ""} onClick={() => setPage(x.page)}>
            {x.page}
          </button>
        ))}
      </div>

      <div className="split">
        <div className="pane">
          <img className="page-img" src={pageImg(cid, st, page)} alt={`page ${page}`} />
        </div>
        <div className="pane">
          <div className="meta">
            source: <b>{p.source}</b> · {p.text.length} chars
          </div>
          <pre className="parsed">{p.text}</pre>
          {p.images?.map((im: any) => (
            <img key={im.id} className="extracted" src={docImg(cid, st, im.id)} alt={im.id} />
          ))}
        </div>
      </div>
    </div>
  );
}
