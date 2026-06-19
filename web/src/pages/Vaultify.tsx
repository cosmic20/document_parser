import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, wsUrl } from "../api";

export default function Vaultify() {
  const { id } = useParams();
  const cid = id!;
  const ref = useRef<HTMLDivElement>(null);
  const [vaultPath, setVaultPath] = useState("");

  useEffect(() => {
    api.config().then((c) => setVaultPath(c.vault || ""));
  }, []);

  useEffect(() => {
    if (!ref.current) return;
    const term = new Terminal({
      cursorBlink: true,
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
      fontSize: 13,
      theme: { background: "#000000" },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(ref.current);
    fit.fit();

    const ws = new WebSocket(wsUrl(`/api/classes/${encodeURIComponent(cid)}/terminal`));
    ws.binaryType = "arraybuffer";
    const enc = new TextEncoder();

    ws.onmessage = (m) => {
      if (typeof m.data === "string") term.write(m.data);
      else term.write(new Uint8Array(m.data));
    };
    ws.onclose = () => term.write("\r\n\x1b[90m[session ended]\x1b[0m\r\n");

    term.onData((d) => ws.readyState === WebSocket.OPEN && ws.send(enc.encode(d)));

    const sendResize = () => {
      fit.fit();
      if (ws.readyState === WebSocket.OPEN)
        ws.send(JSON.stringify({ resize: { cols: term.cols, rows: term.rows } }));
    };
    ws.onopen = () => sendResize();
    window.addEventListener("resize", sendResize);

    return () => {
      window.removeEventListener("resize", sendResize);
      ws.close();
      term.dispose();
    };
  }, [cid]);

  return (
    <div>
      <Link to={`/class/${encodeURIComponent(cid)}`}>← {cid}</Link>
      <h1>Vaultify — {cid}</h1>
      <p className="muted">
        Claude Code is running the <code>vault-build</code> skill against this class's processed
        documents. Watch it work, answer any permission prompts, then open your vault in Obsidian.
      </p>
      <div className="terminal-wrap" ref={ref} />
      {vaultPath && (
        <div className="actions">
          <a className="btn primary" href={`obsidian://open?path=${encodeURIComponent(vaultPath)}`}>
            Open vault in Obsidian
          </a>
          <span className="muted">{vaultPath}</span>
        </div>
      )}
    </div>
  );
}
