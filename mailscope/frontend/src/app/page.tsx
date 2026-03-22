"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { uploadFile } from "@/lib/api";

export default function UploadPage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFile = useCallback((f: File) => {
    const ext = f.name.split(".").pop()?.toLowerCase();
    if (ext !== "eml" && ext !== "msg") {
      setError("Nur .eml und .msg Dateien werden unterstützt.");
      return;
    }
    if (f.size > 25 * 1024 * 1024) {
      setError("Datei überschreitet 25 MB Limit.");
      return;
    }
    setError(null);
    setFile(f);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      if (e.dataTransfer.files.length > 0) {
        handleFile(e.dataTransfer.files[0]);
      }
    },
    [handleFile]
  );

  const handleSubmit = async () => {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const { job_id } = await uploadFile(file);
      router.push(`/jobs/${job_id}`);
    } catch (e: any) {
      setError(e.message || "Upload fehlgeschlagen");
      setUploading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto">
      {/* Privacy warning */}
      <div className="mb-6 rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3">
        <div className="flex items-start gap-2">
          <svg className="w-5 h-5 text-amber-500 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
          </svg>
          <div>
            <p className="text-sm font-medium text-amber-400">Datenschutzhinweis</p>
            <p className="text-xs text-slate-400 mt-1">
              Extrahierte URLs werden zur Reputationsprüfung an externe Dienste (VirusTotal, urlscan.io) übermittelt.
              Die E-Mail selbst wird nicht an Dritte weitergeleitet.
            </p>
          </div>
        </div>
      </div>

      <h2 className="text-2xl font-bold mb-2">E-Mail analysieren</h2>
      <p className="text-slate-400 text-sm mb-6">
        Laden Sie eine .eml oder .msg Datei hoch, um eine Sicherheitsanalyse durchzuführen.
      </p>

      {/* Drop zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => document.getElementById("file-input")?.click()}
        className={`
          relative cursor-pointer rounded-xl border-2 border-dashed p-12 text-center transition-all
          ${dragging ? "border-accent-blue bg-accent-blue/5" : "border-white/10 hover:border-white/20 hover:bg-surface-card/50"}
          ${file ? "border-accent-green/50 bg-accent-green/5" : ""}
        `}
      >
        <input
          id="file-input"
          type="file"
          accept=".eml,.msg"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
        />
        {file ? (
          <div>
            <div className="w-12 h-12 rounded-full bg-accent-green/10 flex items-center justify-center mx-auto mb-3">
              <svg className="w-6 h-6 text-accent-green" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <p className="text-sm font-medium">{file.name}</p>
            <p className="text-xs text-slate-500 mt-1">{(file.size / 1024).toFixed(1)} KB</p>
            <button
              onClick={(e) => {
                e.stopPropagation();
                setFile(null);
              }}
              className="text-xs text-slate-500 hover:text-white mt-2 underline"
            >
              Andere Datei wählen
            </button>
          </div>
        ) : (
          <div>
            <div className="w-12 h-12 rounded-full bg-white/5 flex items-center justify-center mx-auto mb-3">
              <svg className="w-6 h-6 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
            </div>
            <p className="text-sm font-medium">Datei hierhin ziehen</p>
            <p className="text-xs text-slate-500 mt-1">oder klicken zum Auswählen (.eml, .msg)</p>
          </div>
        )}
      </div>

      {error && (
        <div className="mt-4 rounded-lg bg-red-500/10 border border-red-500/30 px-4 py-2.5">
          <p className="text-sm text-red-400">{error}</p>
        </div>
      )}

      <button
        onClick={handleSubmit}
        disabled={!file || uploading}
        className={`
          mt-6 w-full rounded-lg py-3 px-4 text-sm font-semibold transition-all
          ${file && !uploading ? "bg-accent-blue hover:bg-accent-blue/90 text-white" : "bg-white/5 text-slate-500 cursor-not-allowed"}
        `}
      >
        {uploading ? (
          <span className="flex items-center justify-center gap-2">
            <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Wird hochgeladen...
          </span>
        ) : (
          "Analyse starten"
        )}
      </button>
    </div>
  );
}
