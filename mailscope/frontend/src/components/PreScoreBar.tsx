import type { PreScores } from "@/lib/api";

function ScoreRow({ label, score, color }: { label: string; score: number; color: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-slate-500 w-24 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-white/5 overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${Math.min(100, score)}%`, backgroundColor: color }}
        />
      </div>
      <span className="text-xs font-mono text-slate-400 w-8 text-right">{score}</span>
    </div>
  );
}

export default function PreScoreBar({ scores }: { scores: PreScores }) {
  return (
    <div className="rounded-xl border border-white/10 bg-surface-card p-6">
      <h3 className="text-sm font-semibold mb-4 text-slate-300">Deterministische Vorbewertung</h3>
      <div className="space-y-3">
        <ScoreRow label="Phishing" score={scores.phishing_score} color="#ef4444" />
        <ScoreRow label="Werbung" score={scores.advertising_score} color="#3b82f6" />
        <ScoreRow label="Legitimität" score={scores.legitimacy_score} color="#22c55e" />
      </div>
      {Object.keys(scores.breakdown).length > 0 && (
        <details className="mt-4">
          <summary className="text-[11px] text-slate-600 cursor-pointer hover:text-slate-400">
            Score-Aufschlüsselung anzeigen
          </summary>
          <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1">
            {Object.entries(scores.breakdown).map(([key, val]) => (
              <div key={key} className="flex items-center justify-between text-[11px]">
                <span className="text-slate-500">{key.replace(/_/g, " ")}</span>
                <span className="text-slate-400 font-mono">+{val}</span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}
