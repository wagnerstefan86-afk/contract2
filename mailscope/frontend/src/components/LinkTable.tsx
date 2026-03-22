import type { LinkDetail } from "@/lib/api";

function FlagBadge({ active, label }: { active: boolean; label: string }) {
  if (!active) return null;
  return (
    <span className="inline-block text-[10px] font-medium px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 mr-1 mb-1">
      {label}
    </span>
  );
}

function CheckBadge({ service, status, score, verdict }: { service: string; status: string; score: number | null; verdict: string | null }) {
  const label = service === "virustotal" ? "VT" : "urlscan";
  if (status === "error" || status === "timeout") {
    return <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-500/10 text-slate-500 mr-1">{label}: {status}</span>;
  }
  const isMalicious = verdict === "malicious" || (score !== null && score > 0);
  return (
    <span
      className={`text-[10px] px-1.5 py-0.5 rounded mr-1 ${
        isMalicious ? "bg-red-500/10 text-red-400" : "bg-green-500/10 text-green-400"
      }`}
    >
      {label}: {verdict || "pending"}{score !== null && score > 0 ? ` (${score})` : ""}
    </span>
  );
}

export default function LinkTable({ links }: { links: LinkDetail[] }) {
  return (
    <div className="rounded-xl border border-white/10 bg-surface-card p-6">
      <h3 className="text-sm font-semibold mb-4 text-slate-300">
        Link-Analyse ({links.length} {links.length === 1 ? "Link" : "Links"})
      </h3>
      <div className="space-y-4">
        {links.map((link) => (
          <div key={link.id} className="rounded-lg bg-surface/50 border border-white/5 p-4">
            <p className="text-xs text-slate-300 font-mono break-all mb-2">{link.normalized_url}</p>
            {link.original_url !== link.normalized_url && (
              <p className="text-[11px] text-slate-600 break-all mb-2">Original: {link.original_url}</p>
            )}
            <div className="flex flex-wrap mb-2">
              <FlagBadge active={link.display_text_mismatch} label="Text-Mismatch" />
              <FlagBadge active={link.suspicious_tld} label="Verdächtige TLD" />
              <FlagBadge active={link.ip_literal} label="IP-Literal" />
              <FlagBadge active={link.punycode} label="Punycode" />
              <FlagBadge active={link.url_shortener} label="URL-Shortener" />
              <FlagBadge active={link.tracking_heavy} label="Tracking" />
            </div>
            <div className="flex flex-wrap">
              {link.checks.map((c, i) => (
                <CheckBadge key={i} service={c.service} status={c.status} score={c.score} verdict={c.verdict} />
              ))}
            </div>
            {link.final_hostname && (
              <p className="text-[11px] text-slate-600 mt-1">Host: {link.final_hostname}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
