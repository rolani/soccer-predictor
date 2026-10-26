import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import AnalysisPanel from "./AnalysisPanel.jsx";
import GameweekPanel from "./GameweekPanel.jsx";
import LiveFixturesPanel from "./LiveFixturesPanel.jsx";
import RunLog from "./RunLog.jsx";

const MARKETS = [
  "all",
  "Over/Under",
  "Over 1.5 goals",
  "BTTS",
  "No goal",
  "DNB",
  "Double chance",
  "Asian handicap",
  "Corners",
  "1H/2H",
  "Team over 0.5",
  "1X2",
  "Correct score",
];

const SCOPES = [
  { id: "live", label: "Live" },
  { id: "today", label: "Today" },
  { id: "tomorrow", label: "Tomorrow" },
  { id: "window", label: "Next hours" },
  { id: "date", label: "Pick date" },
];

const TICKET_MODES = [
  { id: "hybrid", label: "Hybrid" },
  { id: "singles", label: "Singles" },
  { id: "acca", label: "Acca" },
];

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

function selectLegsFromResult(result) {
  const t = result?.suggested_tickets?.[0];
  if (t) {
    return new Set(t.legs);
  }
  if (result?.picks) {
    return new Set(result.picks.map((_, i) => i));
  }
  return new Set();
}

function ConfidenceBar({ value }) {
  const color =
    value >= 85 ? "bg-emerald-500" : value >= 75 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2 text-sm">
      <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${value}%` }} />
      </div>
      <span className="w-8 text-right tabular-nums">{value}</span>
    </div>
  );
}

function PickCard({ pick, index, selected, onToggle }) {
  const [open, setOpen] = useState(false);
  return (
    <article className="border border-slate-700 rounded-lg p-4 bg-slate-900/60">
      <div className="flex gap-3 items-start">
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onToggle(index)}
          className="mt-1"
        />
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap gap-2 items-baseline justify-between">
            <h3 className="font-semibold text-lg">{pick.match}</h3>
            <span className="text-right">
              {pick.price_available === false || pick.odds == null ? (
                <span className="text-amber-400 text-sm font-medium">No book price</span>
              ) : (
                <>
                  <span className="text-emerald-400 font-mono">@{pick.odds.toFixed(2)}</span>
                  {pick.quoted_odds != null &&
                    Math.abs(pick.quoted_odds - pick.odds) > 0.005 && (
                      <span
                        className="block text-[10px] text-slate-500"
                        title="The agent estimated this price; the server replaced it with the book price."
                      >
                        est. {pick.quoted_odds.toFixed(2)} → corrected
                      </span>
                    )}
                </>
              )}
            </span>
          </div>
          {pick.league && (
            <p className="text-slate-400 text-sm">{pick.league}</p>
          )}
          <p className="text-violet-300 mt-1">{pick.tip}</p>
          <p className="text-slate-300 mt-2 text-sm">{pick.reasoning}</p>
          <ConfidenceBar value={pick.confidence} />
          <p className="text-xs text-slate-500 mt-1">
            Est. {(pick.estimated_probability * 100).toFixed(0)}% · {pick.kickoff_et || "—"}
            {pick.status === "live" && pick.score && ` · ${pick.minute}' ${pick.score}`}
          </p>
          <button
            type="button"
            onClick={() => setOpen(!open)}
            className="text-xs text-slate-400 mt-2 hover:text-slate-200"
          >
            {open ? "Hide" : "Show"} evidence
          </button>
          {open && (
            <ul className="mt-2 text-sm text-slate-400 list-disc pl-5 space-y-1">
              {pick.evidence?.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
              {pick.risks?.length > 0 && (
                <li className="text-amber-500/90 list-none -ml-5">
                  Risks: {pick.risks.join("; ")}
                </li>
              )}
            </ul>
          )}
        </div>
      </div>
    </article>
  );
}

export default function App() {
  const [tab, setTab] = useState("generate");
  const [health, setHealth] = useState(null);
  const [scope, setScope] = useState("today");
  const [hoursWindow, setHoursWindow] = useState(6);
  const [targetDate, setTargetDate] = useState("");
  const [markets, setMarkets] = useState(["all"]);
  const [minOdds, setMinOdds] = useState(1.25);
  const [maxOdds, setMaxOdds] = useState(3.0);
  const [minConfidence, setMinConfidence] = useState(75);
  const [marginBuffer, setMarginBuffer] = useState(0.08);
  const [allQualify, setAllQualify] = useState(true);
  const [maxPicks, setMaxPicks] = useState(6);
  const [ticketMode, setTicketMode] = useState("hybrid");
  const [accaLegs, setAccaLegs] = useState(8);
  const [combinedMin, setCombinedMin] = useState(8);
  const [combinedMax, setCombinedMax] = useState(20);
  const [targetOdds, setTargetOdds] = useState("");
  const [leagueInclude, setLeagueInclude] = useState("");
  const [leagueExclude, setLeagueExclude] = useState("");
  const [model, setModel] = useState("composer-2.5");
  const [models, setModels] = useState(["composer-2.5"]);

  const [running, setRunning] = useState(false);
  const [runId, setRunId] = useState(null);
  const [meta, setMeta] = useState(null);
  const [result, setResult] = useState(null);
  const [log, setLog] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [history, setHistory] = useState([]);
  const [analysis, setAnalysis] = useState(null);
  const [refineText, setRefineText] = useState("");
  const [error, setError] = useState("");
  const [liveBoard, setLiveBoard] = useState(null);
  const [liveLoading, setLiveLoading] = useState(false);
  const esRef = useRef(null);

  useEffect(() => {
    api("/api/health").then(setHealth).catch(() => setHealth({ ok: false }));
    api("/api/models")
      .then((d) => setModels(d.models?.map((m) => m.id) || ["composer-2.5"]))
      .catch(() => {});
  }, []);

  const loadHistory = useCallback(() => {
    api("/api/runs").then((d) => setHistory(d.runs || [])).catch(() => {});
  }, []);

  const loadAnalysis = useCallback(() => {
    api("/api/analysis").then(setAnalysis).catch(() => setAnalysis(null));
  }, []);

  useEffect(() => {
    if (tab === "history") loadHistory();
    if (tab === "analysis") loadAnalysis();
  }, [tab, loadHistory, loadAnalysis]);

  const loadLiveFixtures = useCallback(() => {
    setLiveLoading(true);
    api("/api/live/fixtures")
      .then(setLiveBoard)
      .catch(() => setLiveBoard(null))
      .finally(() => setLiveLoading(false));
  }, []);

  useEffect(() => {
    if (scope !== "live" || tab !== "generate") return;
    loadLiveFixtures();
    const t = setInterval(loadLiveFixtures, 60000);
    return () => clearInterval(t);
  }, [scope, tab, loadLiveFixtures]);

  const toggleMarket = (m) => {
    if (m === "all") {
      setMarkets(["all"]);
      return;
    }
    setMarkets((prev) => {
      const next = prev.filter((x) => x !== "all");
      return next.includes(m) ? next.filter((x) => x !== m) : [...next, m];
    });
  };

  const connectEvents = useCallback(
    (id) => {
      if (esRef.current) esRef.current.close();
      const es = new EventSource(`/api/runs/${id}/events`);
      esRef.current = es;
      es.onmessage = (ev) => {
        const data = JSON.parse(ev.data);
        if (data.type === "connected") return;
        setLog((prev) => [...prev.slice(-200), data]);
        if (data.type === "done" || data.type === "error" || data.type === "cancelled") {
          setRunning(false);
          es.close();
          api(`/api/runs/${id}`)
            .then((d) => {
              setMeta(d.meta);
              setResult(d.result);
              if (d.result) {
                setSelected(selectLegsFromResult(d.result));
              }
            })
            .catch(() => {});
          loadHistory();
        }
      };
      es.onerror = () => {
        setRunning(false);
      };
    },
    [loadHistory]
  );

  const startRun = async () => {
    setError("");
    setLog([]);
    setResult(null);
    setMeta(null);
    setRunning(true);
    try {
      const body = {
        scope,
        hours_window: scope === "window" ? hoursWindow : null,
        target_date: scope === "date" ? targetDate : null,
        markets,
        min_odds: minOdds,
        max_odds: maxOdds,
        min_confidence: minConfidence,
        margin_buffer: marginBuffer,
        max_picks: allQualify ? null : maxPicks,
        all_that_qualify: allQualify,
        ticket_mode: ticketMode,
        acca_legs: accaLegs,
        target_combined_odds_min: combinedMin,
        target_combined_odds_max: combinedMax,
        league_include: leagueInclude,
        league_exclude: leagueExclude,
        model,
        target_odds: targetOdds || null,
      };
      const m = await api("/api/runs", { method: "POST", body: JSON.stringify(body) });
      setRunId(m.id);
      setMeta(m);
      connectEvents(m.id);
    } catch (e) {
      setError(e.message);
      setRunning(false);
    }
  };

  const cancelRun = async () => {
    if (!runId) return;
    await api(`/api/runs/${runId}`, { method: "DELETE" }).catch(() => {});
    setRunning(false);
  };

  const refineRun = async () => {
    if (!runId || !refineText.trim()) return;
    setRunning(true);
    setLog([]);
    await api(`/api/runs/${runId}/refine`, {
      method: "POST",
      body: JSON.stringify({ message: refineText }),
    });
    connectEvents(runId);
    setRefineText("");
  };

  const loadRun = async (id) => {
    setRunId(id);
    const d = await api(`/api/runs/${id}`);
    setMeta(d.meta);
    setResult(d.result);
    if (d.meta?.scope === "gameweek") {
      setTab("gameweek");
    } else {
      setTab("generate");
      if (d.result) {
        setSelected(selectLegsFromResult(d.result));
      }
    }
  };

  const fillFromBoard = async () => {
    if (!runId) return;
    setError("");
    try {
      const body = await api(`/api/runs/${runId}/target-ticket`, {
        method: "POST",
        body: JSON.stringify({ fill: true }),
      });
      setResult(body);
      const t = body.suggested_tickets?.[0];
      if (t) setSelected(new Set(t.legs));
    } catch (e) {
      setError(e.message);
    }
  };

  const togglePick = (i) => {
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(i)) n.delete(i);
      else n.add(i);
      return n;
    });
  };

  const footer = useMemo(() => {
    if (!result?.picks?.length) return null;
    const picks = result.picks.filter((_, i) => selected.has(i));
    const priced = picks.filter((p) => p.price_available !== false && p.odds != null);
    const combined = priced.length
      ? priced.reduce((a, p) => a * p.odds, 1)
      : null;
    const joint = picks.reduce((a, p) => a * p.estimated_probability, 1);
    return { count: picks.length, combined, joint };
  }, [result, selected]);

  return (
    <div className="max-w-5xl mx-auto p-4 pb-32">
      <header className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">Soccer Predictor</h1>
        <p className="text-slate-400 text-sm mt-1">
          Research-first picks · Cursor SDK agent
          {!health?.has_api_key && (
            <span className="text-amber-400 ml-2">— set CURSOR_API_KEY in .env</span>
          )}
        </p>
      </header>

      <nav className="flex gap-2 mb-6 border-b border-slate-800 pb-2">
        {["generate", "history", "analysis", "gameweek"].map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`px-3 py-1.5 rounded capitalize text-sm ${
              tab === t ? "bg-violet-600 text-white" : "text-slate-400 hover:text-white"
            }`}
          >
            {t}
          </button>
        ))}
      </nav>

      {tab === "generate" && (
        <div className="space-y-6">
          {scope === "live" && (
            <LiveFixturesPanel
              board={liveBoard}
              loading={liveLoading}
              onRefresh={loadLiveFixtures}
            />
          )}
          <section className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="text-xs text-slate-400 uppercase tracking-wide">Scope</label>
              <div className="flex flex-wrap gap-2 mt-1">
                {SCOPES.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => setScope(s.id)}
                    className={`px-3 py-1 rounded text-sm ${
                      scope === s.id ? "bg-slate-700" : "bg-slate-800 text-slate-400"
                    }`}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
              {scope === "window" && (
                <input
                  type="number"
                  min={1}
                  max={72}
                  value={hoursWindow}
                  onChange={(e) => setHoursWindow(+e.target.value)}
                  className="mt-2 w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm"
                  placeholder="Hours"
                />
              )}
              {scope === "date" && (
                <input
                  type="date"
                  value={targetDate}
                  onChange={(e) => setTargetDate(e.target.value)}
                  className="mt-2 w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm"
                />
              )}
            </div>

            <div>
              <label className="text-xs text-slate-400 uppercase tracking-wide">Ticket mode</label>
              <div className="flex flex-wrap gap-2 mt-1">
                {TICKET_MODES.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => setTicketMode(t.id)}
                    className={`px-3 py-1 rounded text-sm ${
                      ticketMode === t.id ? "bg-slate-700" : "bg-slate-800 text-slate-400"
                    }`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="sm:col-span-2">
              <label className="text-xs text-slate-400 uppercase tracking-wide">Markets</label>
              <div className="flex flex-wrap gap-1.5 mt-1">
                {MARKETS.map((m) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => toggleMarket(m)}
                    className={`px-2 py-0.5 rounded text-xs ${
                      markets.includes(m) ? "bg-violet-900/80 text-violet-200" : "bg-slate-800 text-slate-500"
                    }`}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="text-xs text-slate-400">Odds {minOdds} – {maxOdds}</label>
              <div className="flex gap-2 mt-1">
                <input type="range" min={1.05} max={3} step={0.05} value={minOdds} onChange={(e) => setMinOdds(+e.target.value)} className="flex-1" />
                <input type="range" min={1.5} max={10} step={0.1} value={maxOdds} onChange={(e) => setMaxOdds(+e.target.value)} className="flex-1" />
              </div>
            </div>

            <div>
              <label className="text-xs text-slate-400">Min confidence {minConfidence}</label>
              <input type="range" min={50} max={95} value={minConfidence} onChange={(e) => setMinConfidence(+e.target.value)} className="w-full mt-1" />
              <label className="text-xs text-slate-400 mt-2 block" title="Your estimated win chance must beat the book's implied probability (1/odds) by at least this much">
                Margin buffer {marginBuffer} (edge above 1/odds)
              </label>
              <input type="range" min={0} max={0.2} step={0.01} value={marginBuffer} onChange={(e) => setMarginBuffer(+e.target.value)} className="w-full mt-1" />
            </div>

            <div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={allQualify} onChange={(e) => setAllQualify(e.target.checked)} />
                All picks that qualify
              </label>
              {!allQualify && (
                <input type="number" min={1} max={50} value={maxPicks} onChange={(e) => setMaxPicks(+e.target.value)} className="mt-1 w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm" />
              )}
            </div>

            <div>
              <label className="text-xs text-slate-400">Model</label>
              <select value={model} onChange={(e) => setModel(e.target.value)} className="w-full mt-1 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm">
                {models.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>

            {(ticketMode === "hybrid" || ticketMode === "acca") && (
              <div className="sm:col-span-2 grid sm:grid-cols-3 gap-2">
                <div>
                  <label className="text-xs text-slate-400">Acca legs</label>
                  <input type="number" min={2} max={15} value={accaLegs} onChange={(e) => setAccaLegs(+e.target.value)} className="w-full mt-1 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm" />
                </div>
                <div>
                  <label className="text-xs text-slate-400">Combined min</label>
                  <input type="number" step={0.5} value={combinedMin} onChange={(e) => setCombinedMin(+e.target.value)} className="w-full mt-1 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm" />
                </div>
                <div>
                  <label className="text-xs text-slate-400">Combined max</label>
                  <input type="number" step={0.5} value={combinedMax} onChange={(e) => setCombinedMax(+e.target.value)} className="w-full mt-1 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm" />
                </div>
              </div>
            )}

            <div>
              <label className="text-xs text-slate-400">Target odds</label>
              <input
                type="number"
                min={1.01}
                step={0.1}
                value={targetOdds}
                onChange={(e) => setTargetOdds(e.target.value)}
                className="w-full mt-1 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm"
              />
            </div>

            <div>
              <label className="text-xs text-slate-400">Include leagues</label>
              <input value={leagueInclude} onChange={(e) => setLeagueInclude(e.target.value)} className="w-full mt-1 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm" placeholder="MLS, EPL…" />
            </div>
            <div>
              <label className="text-xs text-slate-400">Exclude leagues</label>
              <input value={leagueExclude} onChange={(e) => setLeagueExclude(e.target.value)} className="w-full mt-1 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm" />
            </div>
          </section>

          <div className="flex gap-2">
            <button
              type="button"
              onClick={startRun}
              disabled={running || !health?.has_api_key}
              className="px-4 py-2 bg-violet-600 hover:bg-violet-500 disabled:opacity-40 rounded font-medium"
            >
              {running ? "Researching…" : "Generate"}
            </button>
            {running && (
              <button type="button" onClick={cancelRun} className="px-4 py-2 bg-slate-700 rounded">
                Cancel
              </button>
            )}
          </div>

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
              {result.picks?.map((p, i) => (
                <PickCard key={i} pick={p} index={i} selected={selected.has(i)} onToggle={togglePick} />
              ))}
              {result.skipped?.length > 0 && (
                <details className="text-sm text-slate-500">
                  <summary>{result.skipped.length} skipped</summary>
                  <ul className="mt-2 space-y-1 pl-4">
                    {result.skipped.map((s, i) => (
                      <li key={i}>{s.match}: {s.why}</li>
                    ))}
                  </ul>
                </details>
              )}
              {result.suggested_tickets?.length > 0 && (
                <div className="text-sm text-slate-400">
                  <p className="font-medium text-slate-300">Suggested tickets</p>
                  {result.suggested_tickets.map((t, i) => (
                    <p key={i}>{t.label || t.type}: legs {t.legs?.join(", ")} @ {t.combined_odds?.toFixed(2)}</p>
                  ))}
                  {result.suggested_tickets[0].in_band === false && (
                    <button
                      type="button"
                      onClick={fillFromBoard}
                      className="mt-2 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded text-sm text-slate-200"
                    >
                      Fill from board
                    </button>
                  )}
                </div>
              )}

              {runId && meta?.export_paths?.csv && (
                <div className="flex flex-wrap gap-2">
                  <a href={`/api/exports/${runId}/csv`} className="text-sm text-violet-400 underline">Download CSV</a>
                  <a href={`/api/exports/${runId}/txt`} className="text-sm text-violet-400 underline">Download TXT</a>
                </div>
              )}
              {runId && meta?.export_paths?.twitter_full && (
                <div className="flex flex-wrap gap-2">
                  {meta.export_paths.twitter_thread && (
                    <a href={`/api/exports/${runId}/twitter_thread`} className="text-sm text-violet-400 underline">
                      Download thread
                    </a>
                  )}
                  <a href={`/api/exports/${runId}/twitter`} className="text-sm text-violet-400 underline">
                    Download full
                  </a>
                </div>
              )}

              {!running && runId && (
                <div className="flex gap-2 mt-4">
                  <input
                    value={refineText}
                    onChange={(e) => setRefineText(e.target.value)}
                    placeholder="Refine: drop leg 2, add one more under 1.5…"
                    className="flex-1 bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm"
                  />
                  <button type="button" onClick={refineRun} className="px-3 py-2 bg-slate-700 rounded text-sm">
                    Refine
                  </button>
                </div>
              )}
            </section>
          )}
        </div>
      )}

      {tab === "history" && (
        <ul className="space-y-2">
          {history.map((h) => (
            <li key={h.id} className="px-3 py-2 rounded bg-slate-900 border border-slate-800 hover:border-slate-600">
              <button
                type="button"
                onClick={() => loadRun(h.id)}
                className="w-full text-left"
              >
                <span className="font-mono text-sm">{h.id}</span>
                <span className="ml-2 text-xs text-slate-500">{h.status} · {h.pick_count} picks</span>
              </button>
              {(h.export_paths?.twitter_full || h.export_paths?.twitter_thread) && (
                <div className="flex flex-wrap gap-2 mt-1">
                  {h.export_paths.twitter_thread && (
                    <a
                      href={`/api/exports/${h.id}/twitter_thread`}
                      onClick={(e) => e.stopPropagation()}
                      className="text-xs text-violet-400 underline"
                    >
                      Download thread
                    </a>
                  )}
                  {h.export_paths.twitter_full && (
                    <a
                      href={`/api/exports/${h.id}/twitter`}
                      onClick={(e) => e.stopPropagation()}
                      className="text-xs text-violet-400 underline"
                    >
                      Download full
                    </a>
                  )}
                </div>
              )}
            </li>
          ))}
          {!history.length && <p className="text-slate-500 text-sm">No runs yet.</p>}
        </ul>
      )}

      {tab === "analysis" && (
        <AnalysisPanel analysis={analysis} onRefresh={loadAnalysis} />
      )}

      {tab === "gameweek" && (
        <GameweekPanel
          model={model}
          models={models}
          loadedRunId={meta?.scope === "gameweek" ? runId : null}
          loadedResult={meta?.scope === "gameweek" ? result : null}
        />
      )}

      {footer && tab === "generate" && (
        <footer className="fixed bottom-0 left-0 right-0 bg-slate-900/95 border-t border-slate-800 p-4">
          <div className="max-w-5xl mx-auto flex flex-wrap gap-4 items-center justify-between text-sm">
            <span>{footer.count} selected</span>
            <span>
              Combined{" "}
              <strong className="text-emerald-400">
                {footer.combined != null ? `${footer.combined.toFixed(2)}×` : "— (no prices)"}
              </strong>
            </span>
            <span>Est. joint {(footer.joint * 100).toFixed(0)}%</span>
          </div>
        </footer>
      )}
    </div>
  );
}
