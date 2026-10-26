import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import RunLog from "./RunLog.jsx";

const LEAGUE_ORDER = ["EPL", "Bundesliga", "La Liga", "Serie A", "Ligue 1"];

const GENERATE_BODY = {
  scope: "gameweek",
  min_confidence: 0,
  margin_buffer: 0,
  min_odds: 1.01,
  max_odds: 50,
  ticket_mode: "singles",
  markets: ["Correct score"],
  all_that_qualify: true,
};

async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json", ...opts.headers },
    ...opts,
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || r.statusText);
  }
  return r.json();
}

function remainingGroups(board) {
  const fixtures = board?.fixtures || [];
  const groups = new Map();
  for (const f of fixtures) {
    const league = f.league || "Gameweek";
    const round_label = f.round_label || league;
    const key = `${league}\0${round_label}`;
    if (!groups.has(key)) {
      groups.set(key, { league, round_label, count: 0 });
    }
    groups.get(key).count += 1;
  }
  const order = board?.leagues?.length ? board.leagues : LEAGUE_ORDER;
  return [...groups.values()].sort((a, b) => {
    const ia = order.indexOf(a.league);
    const ib = order.indexOf(b.league);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });
}

function groupPicksByLeague(picks) {
  const order = [];
  const map = new Map();
  for (const p of picks || []) {
    const league = p.league || "Gameweek";
    if (!map.has(league)) {
      map.set(league, []);
      order.push(league);
    }
    map.get(league).push(p);
  }
  return order.map((league) => ({ league, picks: map.get(league) }));
}

function ScoreRow({ pick }) {
  const pct =
    pick.estimated_probability != null
      ? `${(pick.estimated_probability * 100).toFixed(0)}%`
      : "—";
  const evidence = pick.evidence?.[0] || "";
  return (
    <article className="border border-slate-700 rounded-lg p-3 bg-slate-900/60">
      <div className="flex flex-wrap gap-2 items-baseline justify-between">
        <h3 className="font-semibold">{pick.match}</h3>
        <span className="text-violet-300">{pick.tip}</span>
        <span className="tabular-nums text-slate-200">{pct}</span>
        {pick.confidence < 70 && (
          <span className="text-xs px-1.5 py-0.5 rounded bg-amber-900/60 text-amber-300">
            low conf
          </span>
        )}
      </div>
      {evidence && <p className="text-sm text-slate-400 mt-1">{evidence}</p>}
    </article>
  );
}

export default function GameweekPanel({ model, models, loadedRunId, loadedResult }) {
  const [localModel, setLocalModel] = useState(model);
  const [board, setBoard] = useState(null);
  const [boardLoading, setBoardLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [runId, setRunId] = useState(loadedRunId ?? null);
  const [result, setResult] = useState(loadedResult ?? null);
  const [log, setLog] = useState([]);
  const [error, setError] = useState("");
  const [copyStatus, setCopyStatus] = useState("");
  const esRef = useRef(null);

  useEffect(() => {
    setLocalModel(model);
  }, [model]);

  useEffect(() => {
    if (!loadedRunId) return;
    setRunId(loadedRunId);
    setResult(loadedResult || null);
  }, [loadedRunId, loadedResult]);

  const loadBoard = useCallback(() => {
    setBoardLoading(true);
    api("/api/gameweek/board")
      .then(setBoard)
      .catch((e) => {
        setBoard(null);
        setError(e.message);
      })
      .finally(() => setBoardLoading(false));
  }, []);

  useEffect(() => {
    loadBoard();
    return () => esRef.current?.close();
  }, [loadBoard]);

  const groups = useMemo(() => remainingGroups(board), [board]);
  const remaining = board?.remaining ?? groups.reduce((n, g) => n + g.count, 0);
  const unconfirmed =
    !!board?.unconfirmed_slate ||
    (board?.fixtures || []).some((f) => f.unconfirmed_slate);
  const hasPicks = (result?.picks?.length || 0) > 0;
  const leagueBlocks = useMemo(
    () => groupPicksByLeague(result?.picks),
    [result]
  );

  const connectEvents = useCallback((id) => {
    esRef.current?.close();
    const es = new EventSource(`/api/runs/${id}/events`);
    esRef.current = es;
    es.onmessage = (ev) => {
      const data = JSON.parse(ev.data);
      if (data.type === "connected") return;
      setLog((prev) => [...prev.slice(-200), data]);
      if (["done", "error", "cancelled"].includes(data.type)) {
        setRunning(false);
        es.close();
        api(`/api/runs/${id}`)
          .then((d) => setResult(d.result))
          .catch(() => {});
      }
    };
    es.onerror = () => setRunning(false);
  }, []);

  const generateScores = async () => {
    setError("");
    setCopyStatus("");
    setLog([]);
    setResult(null);
    setRunning(true);
    try {
      const body = {
        ...GENERATE_BODY,
        model: localModel || model,
      };
      const m = await api("/api/runs", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setRunId(m.id);
      connectEvents(m.id);
    } catch (e) {
      setError(e.message);
      setRunning(false);
    }
  };

  const copyExport = async (fmt) => {
    if (!runId || !hasPicks) return;
    setCopyStatus("");
    try {
      const r = await fetch(`/api/exports/${runId}/${fmt}`);
      const text = await r.text();
      if (!r.ok) throw new Error(text || r.statusText);
      await navigator.clipboard.writeText(text);
      setCopyStatus(fmt === "twitter_thread" ? "Thread copied" : "Full copy copied");
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className="space-y-4">
      <section className="border border-slate-800 rounded-lg p-4 bg-slate-900/60">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <div>
            <h2 className="text-sm font-semibold text-violet-200">Remaining round</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              {boardLoading
                ? "Loading slate…"
                : `${remaining} remaining · EPL · Bundesliga · La Liga · Serie A · Ligue 1`}
            </p>
          </div>
          <button
            type="button"
            onClick={loadBoard}
            className="text-xs px-2 py-1 rounded bg-slate-800 text-slate-300 hover:bg-slate-700"
          >
            Refresh
          </button>
        </div>

        {unconfirmed && (
          <p className="text-amber-400 text-sm border border-amber-800/50 rounded p-3 bg-amber-950/20 mb-3">
            Unconfirmed slate — only one calendar responded. Every fixture is flagged.
          </p>
        )}

        {board?.source_errors?.length > 0 && (
          <ul className="text-amber-400/90 text-sm mb-3 space-y-1">
            {board.source_errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        )}

        {!boardLoading && remaining === 0 && (
          <p className="text-slate-400 text-sm mb-3">
            No remaining fixtures this round. Generate is not needed.
          </p>
        )}

        {groups.length > 0 && (
          <ul className="grid gap-2 sm:grid-cols-2 text-sm mb-3">
            {groups.map((g) => (
              <li
                key={`${g.league}-${g.round_label}`}
                className="flex justify-between gap-2 border border-slate-800 rounded px-3 py-2 bg-slate-950/40"
              >
                <span>
                  <span className="text-slate-200">{g.league}</span>
                  {g.round_label && g.round_label !== g.league && (
                    <span className="text-slate-500 ml-2">{g.round_label}</span>
                  )}
                </span>
                <span className="tabular-nums text-slate-400">{g.count} remaining</span>
              </li>
            ))}
          </ul>
        )}

        <div className="flex flex-wrap items-end gap-3">
          {models?.length > 0 && (
            <div className="min-w-[12rem]">
              <label className="text-xs text-slate-400">Model</label>
              <select
                value={localModel}
                onChange={(e) => setLocalModel(e.target.value)}
                className="w-full mt-1 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm"
              >
                {models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>
          )}
          <button
            type="button"
            onClick={generateScores}
            disabled={running || remaining === 0}
            className="px-4 py-2 bg-violet-600 hover:bg-violet-500 disabled:opacity-40 rounded font-medium"
          >
            {running ? "Researching…" : "Generate scores"}
          </button>
        </div>
      </section>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      {(running || log.length > 0) && (
        <section>
          <h2 className="text-sm font-medium text-slate-400 mb-2">Research log</h2>
          <RunLog entries={log} />
        </section>
      )}

      {result && (
        <section className="space-y-4">
          {result.summary && (
            <p className="text-slate-300 border-l-2 border-violet-500 pl-3">{result.summary}</p>
          )}

          {leagueBlocks.map(({ league, picks }) => (
            <div key={league} className="space-y-2">
              <h3 className="text-sm font-semibold text-slate-200 border-b border-slate-800 pb-1">
                {league}
              </h3>
              {picks.map((p, i) => (
                <ScoreRow key={`${league}-${i}`} pick={p} />
              ))}
            </div>
          ))}

          {result.skipped?.length > 0 && (
            <details className="text-sm text-slate-500">
              <summary>{result.skipped.length} skipped</summary>
              <ul className="mt-2 space-y-1 pl-4">
                {result.skipped.map((s, i) => (
                  <li key={i}>
                    {s.match}: {s.why}
                  </li>
                ))}
              </ul>
            </details>
          )}

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={!hasPicks}
              onClick={() => copyExport("twitter_thread")}
              className="px-3 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-40 rounded text-sm"
            >
              Copy thread
            </button>
            <button
              type="button"
              disabled={!hasPicks}
              onClick={() => copyExport("twitter")}
              className="px-3 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-40 rounded text-sm"
            >
              Copy full
            </button>
            {copyStatus && <span className="text-sm text-emerald-400 self-center">{copyStatus}</span>}
          </div>
        </section>
      )}
    </div>
  );
}
