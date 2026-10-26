const VERIFY_LINKS = [
  { label: "LiveScore", url: "https://www.livescore.com/en/football/live/" },
  { label: "FlashScore", url: "https://www.flashscore.com/" },
  { label: "Sofascore", url: "https://www.sofascore.com/" },
  { label: "FotMob", url: "https://www.fotmob.com/live" },
];

export default function LiveFixturesPanel({ board, loading, onRefresh }) {
  if (loading && !board) {
    return <p className="text-slate-500 text-sm">Loading live games…</p>;
  }

  const count = board?.in_play_count ?? 0;
  const fixtures = board?.fixtures ?? [];

  return (
    <section className="border border-violet-900/50 rounded-lg p-4 bg-violet-950/20 mb-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div>
          <h2 className="text-sm font-semibold text-violet-200">Live now (ESPN)</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            {count} in play · agent verifies Sofascore / FlashScore / LiveScore before picks
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="text-xs px-2 py-1 rounded bg-slate-800 text-slate-300 hover:bg-slate-700"
        >
          Refresh
        </button>
      </div>

      {count === 0 ? (
        <p className="text-sm text-slate-400">
          No in-play games on ESPN right now. Still check{" "}
          {VERIFY_LINKS.map((l, i) => (
            <span key={l.label}>
              {i > 0 && ", "}
              <a href={l.url} target="_blank" rel="noreferrer" className="text-violet-400 underline">
                {l.label}
              </a>
            </span>
          ))}{" "}
          before generating — leagues can differ.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="text-slate-500 text-left">
                <th className="py-1 pr-2">League</th>
                <th className="py-1 pr-2">Match</th>
                <th className="py-1 pr-2">Min</th>
                <th className="py-1 pr-2">Score</th>
                <th className="py-1">Status</th>
              </tr>
            </thead>
            <tbody>
              {fixtures.map((f, i) => (
                <tr key={i} className="border-t border-slate-800 text-slate-300">
                  <td className="py-1.5 pr-2 text-slate-400">{f.league}</td>
                  <td className="py-1.5 pr-2">
                    {f.detail_url ? (
                      <a href={f.detail_url} target="_blank" rel="noreferrer" className="hover:text-violet-300">
                        {f.match}
                      </a>
                    ) : (
                      f.match
                    )}
                  </td>
                  <td className="py-1.5 pr-2 font-mono">{f.minute}</td>
                  <td className="py-1.5 pr-2 font-mono">{f.score}</td>
                  <td className="py-1.5 text-slate-500">{f.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-slate-600 mt-3">
        Verify stats:{" "}
        {VERIFY_LINKS.map((l) => (
          <a
            key={l.label}
            href={l.url}
            target="_blank"
            rel="noreferrer"
            className="text-violet-400/80 underline mr-2"
          >
            {l.label}
          </a>
        ))}
      </p>
    </section>
  );
}
