import type { ServiceFlags } from "@/lib/api";

function Badge({ label, enabled }: { label: string; enabled: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-[11px] font-medium px-2 py-1 rounded-full ${
        enabled
          ? "bg-accent-green/10 text-accent-green border border-accent-green/20"
          : "bg-white/5 text-slate-500 border border-white/10"
      }`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${enabled ? "bg-accent-green" : "bg-slate-600"}`} />
      {label}: {enabled ? "aktiv" : "deaktiviert"}
    </span>
  );
}

export default function ServiceBadges({ services }: { services: ServiceFlags }) {
  return (
    <div className="flex flex-wrap gap-2">
      <Badge label="VirusTotal" enabled={services.vt_enabled} />
      <Badge label="urlscan.io" enabled={services.urlscan_enabled} />
      <Badge label="KI-Bewertung" enabled={services.llm_enabled} />
    </div>
  );
}
