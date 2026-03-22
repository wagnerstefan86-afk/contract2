import type { HeaderFinding } from "@/lib/api";

const SEVERITY_CONFIG: Record<string, { color: string; bg: string }> = {
  critical: { color: "text-red-400", bg: "bg-red-500/10" },
  warning: { color: "text-amber-400", bg: "bg-amber-500/10" },
  info: { color: "text-blue-400", bg: "bg-blue-500/10" },
};

export default function HeaderFindings({ findings }: { findings: HeaderFinding[] }) {
  // Sort: critical first, then warning, then info
  const order = { critical: 0, warning: 1, info: 2 };
  const sorted = [...findings].sort(
    (a, b) => (order[a.severity as keyof typeof order] ?? 3) - (order[b.severity as keyof typeof order] ?? 3)
  );

  return (
    <div className="rounded-xl border border-white/10 bg-surface-card p-6">
      <h3 className="text-sm font-semibold mb-4 text-slate-300">Header-Analyse</h3>
      <div className="space-y-3">
        {sorted.map((f) => {
          const cfg = SEVERITY_CONFIG[f.severity] || SEVERITY_CONFIG.info;
          return (
            <div key={f.id} className="flex items-start gap-3">
              <span
                className={`shrink-0 mt-0.5 text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${cfg.bg} ${cfg.color}`}
              >
                {f.severity}
              </span>
              <div className="min-w-0">
                <p className="text-sm font-medium text-slate-200">{f.title}</p>
                <p className="text-xs text-slate-500 mt-0.5 break-words">{f.detail}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
