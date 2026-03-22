"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { getJobStatus, getJobResult, fetchExport, type JobStatus, type JobResult, type ServiceFlags } from "@/lib/api";
import VerdictCard from "@/components/VerdictCard";
import HeaderFindings from "@/components/HeaderFindings";
import LinkTable from "@/components/LinkTable";
import Accordion from "@/components/Accordion";
import SenderInfo from "@/components/SenderInfo";
import PreScoreBar from "@/components/PreScoreBar";
import ServiceBadges from "@/components/ServiceBadges";

const STAGE_LABELS: Record<string, string> = {
  queued: "In Warteschlange",
  parsing: "E-Mail wird geparst",
  extracting_links: "Links werden extrahiert",
  checking_reputation: "URLs werden geprüft (VT/urlscan)",
  llm_assessment: "KI-Bewertung läuft",
  completed: "Analyse abgeschlossen",
  completed_with_warnings: "Analyse abgeschlossen (mit Hinweisen)",
  failed: "Fehler aufgetreten",
};

const STAGE_ORDER = ["queued", "parsing", "extracting_links", "checking_reputation", "llm_assessment", "completed"];
const TERMINAL_STATUSES = new Set(["completed", "completed_with_warnings", "failed"]);

function StatusProgress({ status }: { status: string }) {
  const displayStatus = status === "completed_with_warnings" ? "completed" : status;
  const currentIdx = STAGE_ORDER.indexOf(displayStatus);
  const isError = status === "failed";

  return (
    <div className="space-y-3">
      {STAGE_ORDER.map((stage, idx) => {
        const isComplete = currentIdx > idx;
        const isCurrent = currentIdx === idx;
        return (
          <div key={stage} className="flex items-center gap-3">
            <div
              className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
                isComplete
                  ? "bg-accent-green/20 text-accent-green"
                  : isCurrent
                  ? isError
                    ? "bg-accent-red/20 text-accent-red"
                    : "bg-accent-blue/20 text-accent-blue animate-pulse"
                  : "bg-white/5 text-slate-600"
              }`}
            >
              {isComplete ? (
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
              ) : (
                idx + 1
              )}
            </div>
            <span
              className={`text-sm ${
                isComplete ? "text-slate-400" : isCurrent ? "text-white font-medium" : "text-slate-600"
              }`}
            >
              {STAGE_LABELS[stage]}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export default function JobPage() {
  const params = useParams();
  const jobId = params.id as string;
  const [status, setStatus] = useState<JobStatus | null>(null);
  const [result, setResult] = useState<JobResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [maskEmails, setMaskEmails] = useState(false);

  const maskEmail = useCallback(
    (email: string | null | undefined) => {
      if (!email || !maskEmails) return email || "";
      return email.replace(/([^@]{2})[^@]*(@.*)/, "$1***$2");
    },
    [maskEmails]
  );

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout>;

    const poll = async () => {
      try {
        const s = await getJobStatus(jobId);
        if (cancelled) return;
        setStatus(s);

        if (TERMINAL_STATUSES.has(s.status)) {
          const r = await getJobResult(jobId);
          if (!cancelled) setResult(r);
          return;
        }

        timeoutId = setTimeout(poll, 2000);
      } catch (e: any) {
        if (!cancelled) setError(e.message);
      }
    };

    poll();
    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
    };
  }, [jobId]);

  if (error) {
    return (
      <div className="max-w-3xl mx-auto">
        <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-6">
          <p className="text-red-400 font-medium">Fehler</p>
          <p className="text-sm text-slate-400 mt-1">{error}</p>
        </div>
      </div>
    );
  }

  if (!status) {
    return (
      <div className="flex items-center justify-center py-20">
        <svg className="w-6 h-6 animate-spin text-accent-blue" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      </div>
    );
  }

  const isDone = TERMINAL_STATUSES.has(status.status) && result;
  const warnings = result?.warnings || status.warnings || [];

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h2 className="text-xl font-bold">{status.filename}</h2>
          {status.subject && <p className="text-sm text-slate-400 mt-1">{status.subject}</p>}
        </div>
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-xs text-slate-500 cursor-pointer">
            <input
              type="checkbox"
              checked={maskEmails}
              onChange={(e) => setMaskEmails(e.target.checked)}
              className="rounded border-slate-600 bg-surface-card"
            />
            E-Mail-Adressen maskieren
          </label>
          {isDone && (
            <button
              onClick={async () => {
                try {
                  const data = await fetchExport(jobId);
                  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `mailscope-${jobId}.json`;
                  a.click();
                  URL.revokeObjectURL(url);
                } catch (e: any) {
                  alert(e.message || "Export fehlgeschlagen");
                }
              }}
              className="flex items-center gap-1.5 text-xs font-medium text-accent-blue hover:text-accent-blue/80 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              JSON Export
            </button>
          )}
        </div>
      </div>

      {/* Service badges */}
      {(status.services || result?.services) && (
        <ServiceBadges services={result?.services || status.services} />
      )}

      {/* Warnings */}
      {warnings.length > 0 && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3">
          <p className="text-xs font-medium text-amber-400 mb-1">Hinweise</p>
          <ul className="space-y-0.5">
            {warnings.map((w, i) => (
              <li key={i} className="text-xs text-slate-400 flex items-start gap-1.5">
                <span className="text-amber-500 mt-0.5">•</span>{w}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Progress */}
      {!isDone && (
        <div className="rounded-xl border border-white/10 bg-surface-card p-6">
          <h3 className="text-sm font-semibold mb-4 text-slate-300">Analyse-Fortschritt</h3>
          <StatusProgress status={status.status} />
          {status.error_message && (
            <div className="mt-4 rounded-lg bg-red-500/10 border border-red-500/30 px-4 py-2.5">
              <p className="text-sm text-red-400">{status.error_message}</p>
            </div>
          )}
        </div>
      )}

      {/* Results */}
      {isDone && result && (
        <>
          {/* Verdict */}
          {result.assessment && <VerdictCard assessment={result.assessment} />}

          {/* Pre-scores */}
          {result.pre_scores && <PreScoreBar scores={result.pre_scores} />}

          {/* Sender info */}
          <SenderInfo
            sender={maskEmail(result.sender)}
            replyTo={maskEmail(result.reply_to)}
            returnPath={maskEmail(result.return_path)}
            to={maskEmail(result.to_address)}
            date={result.date}
            messageId={result.message_id}
          />

          {/* Header findings */}
          {result.header_findings.length > 0 && <HeaderFindings findings={result.header_findings} />}

          {/* Links */}
          {result.links.length > 0 && <LinkTable links={result.links} />}

          {/* Analyst summary */}
          {result.assessment?.analyst_summary && (
            <div className="rounded-xl border border-white/10 bg-surface-card p-6">
              <h3 className="text-sm font-semibold mb-3 text-slate-300">Analysteneinschätzung</h3>
              <p className="text-sm text-slate-300 leading-relaxed">{result.assessment.analyst_summary}</p>
            </div>
          )}

          {/* Attachments */}
          {result.attachment_metadata.length > 0 && (
            <div className="rounded-xl border border-white/10 bg-surface-card p-6">
              <h3 className="text-sm font-semibold mb-3 text-slate-300">Anhänge</h3>
              <div className="space-y-2">
                {result.attachment_metadata.map((att, i) => (
                  <div key={i} className="flex items-center gap-3 text-sm">
                    <svg className="w-4 h-4 text-slate-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                    </svg>
                    <span className="text-slate-300">{att.filename}</span>
                    <span className="text-slate-600 text-xs">{att.content_type}</span>
                    <span className="text-slate-600 text-xs">{(att.size / 1024).toFixed(1)} KB</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Technical details accordion */}
          <Accordion title="Technische Details">
            <div className="space-y-4">
              {result.authentication_results && (
                <div>
                  <p className="text-xs font-medium text-slate-500 mb-1">Authentication-Results</p>
                  <pre className="text-xs text-slate-400 whitespace-pre-wrap bg-surface/50 rounded-lg p-3">
                    {result.authentication_results}
                  </pre>
                </div>
              )}
              {result.received_chain.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-slate-500 mb-1">Received Chain ({result.received_chain.length} Hops)</p>
                  {result.received_chain.map((r, i) => (
                    <pre key={i} className="text-xs text-slate-400 whitespace-pre-wrap bg-surface/50 rounded-lg p-2 mb-1">
                      {r}
                    </pre>
                  ))}
                </div>
              )}
              {result.body_text && (
                <div>
                  <p className="text-xs font-medium text-slate-500 mb-1">Text-Inhalt (Auszug)</p>
                  <pre className="text-xs text-slate-400 whitespace-pre-wrap bg-surface/50 rounded-lg p-3 max-h-40 overflow-auto">
                    {result.body_text.slice(0, 2000)}
                  </pre>
                </div>
              )}
            </div>
          </Accordion>

          {/* Raw headers accordion */}
          <Accordion title="Rohe Header">
            <pre className="text-xs text-slate-400 whitespace-pre-wrap bg-surface/50 rounded-lg p-3 max-h-80 overflow-auto">
              {result.raw_headers}
            </pre>
          </Accordion>
        </>
      )}
    </div>
  );
}
