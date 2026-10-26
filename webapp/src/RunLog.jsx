import { useEffect, useRef } from "react";

export default function RunLog({ entries }) {
  const ref = useRef(null);

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [entries]);

  return (
    <div
      ref={ref}
      className="h-40 overflow-y-auto bg-slate-900 border border-slate-800 rounded p-2 text-xs font-mono space-y-1"
    >
      {entries.map((l, i) => (
        <div key={i} className="text-slate-400">
          {l.type === "tool" && `[tool] ${l.name} (${l.status})`}
          {l.type === "thinking" && `[…] ${l.text?.slice(0, 120)}`}
          {l.type === "assistant" && l.text?.slice(0, 200)}
          {l.type === "status" && l.text}
          {l.type === "error" && <span className="text-red-400">{l.message}</span>}
          {l.type === "done" && <span className="text-emerald-400">Done — {l.status}</span>}
        </div>
      ))}
    </div>
  );
}
