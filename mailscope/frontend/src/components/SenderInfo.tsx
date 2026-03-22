interface Props {
  sender: string;
  replyTo: string;
  returnPath: string;
  to: string;
  date: string | null;
  messageId: string | null;
}

function Row({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div className="flex items-start gap-3 text-sm">
      <span className="shrink-0 w-28 text-slate-500 text-xs font-medium">{label}</span>
      <span className="text-slate-300 break-all">{value}</span>
    </div>
  );
}

export default function SenderInfo({ sender, replyTo, returnPath, to, date, messageId }: Props) {
  return (
    <div className="rounded-xl border border-white/10 bg-surface-card p-6">
      <h3 className="text-sm font-semibold mb-4 text-slate-300">Absenderinformationen</h3>
      <div className="space-y-2">
        <Row label="Von" value={sender} />
        <Row label="An" value={to} />
        {replyTo && <Row label="Reply-To" value={replyTo} />}
        {returnPath && <Row label="Return-Path" value={returnPath} />}
        <Row label="Datum" value={date} />
        <Row label="Message-ID" value={messageId} />
      </div>
    </div>
  );
}
