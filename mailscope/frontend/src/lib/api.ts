const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const TOKEN_STORAGE_KEY = "mailscope_app_token";

export function getStoredToken(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(TOKEN_STORAGE_KEY) || "";
}

export function setStoredToken(token: string): void {
  if (typeof window === "undefined") return;
  if (token) {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
  }
}

function authHeaders(): Record<string, string> {
  const token = getStoredToken();
  return token ? { "X-App-Token": token } : {};
}

export interface ServiceFlags {
  vt_enabled: boolean;
  urlscan_enabled: boolean;
  llm_enabled: boolean;
}

export interface JobStatus {
  id: string;
  filename: string;
  status: string;
  error_message: string | null;
  warnings: string[];
  subject: string | null;
  sender: string | null;
  reply_to: string | null;
  return_path: string | null;
  to_address: string | null;
  date: string | null;
  message_id: string | null;
  link_count: number;
  services: ServiceFlags;
  created_at: string | null;
  updated_at: string | null;
}

export interface LinkCheck {
  service: string;
  status: string;
  score: number | null;
  verdict: string | null;
  summary: Record<string, any> | null;
}

export interface LinkDetail {
  id: string;
  original_url: string;
  normalized_url: string;
  final_hostname: string | null;
  display_text: string | null;
  display_text_mismatch: boolean;
  suspicious_tld: boolean;
  ip_literal: boolean;
  punycode: boolean;
  url_shortener: boolean;
  tracking_heavy: boolean;
  link_findings: Record<string, any> | null;
  checks: LinkCheck[];
}

export interface HeaderFinding {
  id: string;
  severity: string;
  title: string;
  detail: string;
}

export interface PreScores {
  phishing_score: number;
  advertising_score: number;
  legitimacy_score: number;
  breakdown: Record<string, number>;
}

export interface Assessment {
  source: string;
  classification: string | null;
  risk_score: number | null;
  confidence: number | null;
  recommended_action: string | null;
  rationale: string | null;
  evidence: string[];
  analyst_summary: string | null;
}

export interface JobResult {
  id: string;
  filename: string;
  status: string;
  error_message: string | null;
  warnings: string[];
  subject: string | null;
  sender: string | null;
  reply_to: string | null;
  return_path: string | null;
  to_address: string | null;
  date: string | null;
  message_id: string | null;
  authentication_results: string | null;
  received_chain: string[];
  raw_headers: string | null;
  structured_headers: Record<string, string[]> | null;
  body_text: string | null;
  attachment_metadata: Array<{ filename: string; content_type: string; size: number }>;
  header_findings: HeaderFinding[];
  pre_scores: PreScores | null;
  links: LinkDetail[];
  assessment: Assessment | null;
  services: ServiceFlags;
  created_at: string | null;
}

export async function uploadFile(file: File): Promise<{ job_id: string }> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/api/upload`, {
    method: "POST",
    headers: authHeaders(),
    body: formData,
  });
  if (!res.ok) {
    if (res.status === 401) throw new Error("Zugangstoken ungültig oder fehlend.");
    const err = await res.json().catch(() => ({ detail: "Upload fehlgeschlagen" }));
    throw new Error(err.detail || "Upload fehlgeschlagen");
  }
  return res.json();
}

export async function getJobStatus(jobId: string): Promise<JobStatus> {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}`, { headers: authHeaders() });
  if (res.status === 401) throw new Error("Zugangstoken ungültig oder fehlend.");
  if (!res.ok) throw new Error("Job nicht gefunden");
  return res.json();
}

export async function getJobResult(jobId: string): Promise<JobResult> {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}/result`, { headers: authHeaders() });
  if (res.status === 401) throw new Error("Zugangstoken ungültig oder fehlend.");
  if (!res.ok) throw new Error("Ergebnis nicht gefunden");
  return res.json();
}

export function getExportUrl(jobId: string): string {
  return `${API_BASE}/api/jobs/${jobId}/export`;
}

export async function fetchExport(jobId: string): Promise<object> {
  const res = await fetch(getExportUrl(jobId), { headers: authHeaders() });
  if (res.status === 401) throw new Error("Zugangstoken ungültig oder fehlend.");
  if (!res.ok) throw new Error("Export fehlgeschlagen");
  return res.json();
}
