import type { Assessment } from "@/lib/api";

const CLASS_CONFIG: Record<string, { label: string; color: string; bg: string; border: string }> = {
  phishing: { label: "Phishing", color: "text-red-400", bg: "bg-red-500/10", border: "border-red-500/30" },
  suspicious: { label: "Verdächtig", color: "text-amber-400", bg: "bg-amber-500/10", border: "border-amber-500/30" },
  advertising: { label: "Werbung / Newsletter", color: "text-blue-400", bg: "bg-blue-500/10", border: "border-blue-500/30" },
  legitimate: { label: "Legitim", color: "text-green-400", bg: "bg-green-500/10", border: "border-green-500/30" },
  unknown: { label: "Unbekannt", color: "text-slate-400", bg: "bg-slate-500/10", border: "border-slate-500/30" },
};

const ACTION_LABELS: Record<string, string> = {
  delete: "E-Mail löschen",
  open_ticket: "Sicherheitsticket eröffnen",
  verify_via_known_channel: "Absender über bekannten Kanal verifizieren",
  allow: "Zulassen",
  manual_review: "Manuelle Prüfung erforderlich",
};

function RiskGauge({ score }: { score: number }) {
  const pct = Math.min(100, Math.max(0, score));
  const color =
    pct >= 80 ? "#ef4444" : pct >= 60 ? "#f59e0b" : pct >= 40 ? "#eab308" : pct >= 20 ? "#3b82f6" : "#22c55e";

  return (
    <div className="flex items-center gap-3">
      <div className="flex-1 h-2 rounded-full bg-white/5 overflow-hidden">
        <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
      <span className="text-lg font-bold tabular-nums" style={{ color }}>
        {score}
      </span>
    </div>
  );
}

export default function VerdictCard({ assessment }: { assessment: Assessment }) {
  const cls = CLASS_CONFIG[assessment.classification || "unknown"] || CLASS_CONFIG.unknown;

  return (
    <div className={`rounded-xl border ${cls.border} ${cls.bg} p-6`}>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Classification */}
        <div>
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-1">Klassifikation</p>
          <span className={`text-xl font-bold ${cls.color}`}>{cls.label}</span>
        </div>

        {/* Risk score */}
        <div>
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">Risikoscore</p>
          <RiskGauge score={assessment.risk_score || 0} />
          <p className="text-xs text-slate-600 mt-1">Konfidenz: {assessment.confidence || 0}%</p>
        </div>

        {/* Action */}
        <div>
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-1">Handlungsempfehlung</p>
          <p className="text-sm font-semibold text-slate-200">
            {ACTION_LABELS[assessment.recommended_action || ""] || assessment.recommended_action}
          </p>
        </div>
      </div>

      {/* Rationale */}
      {assessment.rationale && (
        <div className="mt-4 pt-4 border-t border-white/5">
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">Kurzbegründung</p>
          <p className="text-sm text-slate-300 leading-relaxed">{assessment.rationale}</p>
        </div>
      )}

      {/* Evidence */}
      {assessment.evidence.length > 0 && (
        <div className="mt-3 pt-3 border-t border-white/5">
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">Evidenz</p>
          <ul className="space-y-1">
            {assessment.evidence.map((e, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-slate-400">
                <span className="text-slate-600 mt-0.5">•</span>
                {e}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
