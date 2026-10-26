import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import RunLog from "./RunLog.jsx";

async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json", ...opts.headers },
    ...opts,
  });
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}

export default function AnalysisPanel({ analysis, onRefresh }) {
  const [status, setStatus] = useState(null);
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState([]);
  const [error, setError] = useState("");
  const esRef = useRef(null);

  const loadStatus = useCallback(() => {
    api("/api/analysis/status")
      .then((s) => {
        setStatus(s);
        setRunning(!!s.running);
      })
      .catch(() => setStatus(null));
  }, []);

  useEffect(() => {
    loadStatus();
    return () => esRef.current?.close();
  }, [loadStatus]);

  const startAnalysis = async () => {
    setError("");
    setLog([]);
    setRunning(true);
    try {
      const { run_id: runId } = await api("/api/analysis/run", { method: "POST" });
      esRef.current?.close();
      const es = new EventSource(`/api/runs/${runId}/events`);
      esRef.current = es;
      es.onmessage = (ev) => {
        const data = JSON.parse(ev.data);
        if (data.type === "connected") return;
        setLog((prev) => [...prev.slice(-200), data]);
        if (["done", "error", "cancelled"].includes(data.type)) {
          setRunning(false);
          es.close();
          onRefresh?.();
          loadStatus();
        }
      };
      es.onerror = () => setRunning(false);
    } catch (e) {
      setError(e.message);
      setRunning(false);
    }
  };

  const ungraded = status?.ungraded?.length ?? 0;

  return (
    <div className="space-y-4">
      <section className="flex flex-wrap items-center gap-3 border border-slate-800 rounded-lg p-4 bg-slate-900/60">
        <button
          type="button"
          onClick={startAnalysis}
          disabled={running || ungraded === 0}
          className="px-4 py-2 bg-violet-600 hover:bg-violet-500 disabled:opacity-40 rounded font-medium"
        >
          {running ? "Grading…" : "Run analysis"}
        </button>
        <p className="text-sm text-slate-400">
          {ungraded === 0
            ? "Nothing to grade — every finished run is already in MASTER."
            : `${ungraded} finished run${ungraded === 1 ? "" : "s"} waiting to be graded.`}
          {status?.last_graded_at && (
            <span className="block text-xs text-slate-500">
              Last graded {new Date(status.last_graded_at).toLocaleString()}
            </span>
          )}
        </p>
      </section>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      {(running || log.length > 0) && (
        <section>
          <h2 className="text-sm font-medium text-slate-400 mb-2">Analysis log</h2>
          <RunLog entries={log} />
        </section>
      )}

      {!analysis?.sections || Object.keys(analysis.sections).length === 0 ? (
        <p className="text-slate-500 text-sm">
          No MASTER.md yet. Run predictions-analysis after results.
        </p>
      ) : (
        <div className="space-y-8">
          {Object.entries(analysis.sections)
            .filter(([, body]) => body && body.trim())
            .map(([title, body]) => (
              <section key={title} className="analysis-md">
                {title !== "intro" && (
                  <h2 className="text-lg font-semibold text-slate-100 mb-3 border-b border-slate-800 pb-2">
                    {title}
                  </h2>
                )}
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown>
              </section>
            ))}
        </div>
      )}
    </div>
  );
}
