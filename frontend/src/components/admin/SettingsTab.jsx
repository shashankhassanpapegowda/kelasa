import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Database, DownloadSimple, ShieldWarning, ArrowClockwise } from "@phosphor-icons/react";

const fmtSize = (b) => (b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round((b || 0) / 1024))} KB`);
const stampName = (iso) => {
  const d = new Date(iso || Date.now());
  const p = (n) => String(n).padStart(2, "0");
  return `kelasa-export-${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}.zip`;
};

export const DataExportCard = () => {
  const [job, setJob] = useState(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef(null);

  const poll = (id) => {
    clearTimeout(timer.current);
    api.get(`/admin/export/status/${id}`).then(r => {
      setJob(r.data);
      if (r.data.status === "running") timer.current = setTimeout(() => poll(id), 1500);
    }).catch(() => toast.error("Lost track of the export"));
  };
  useEffect(() => {
    api.get("/admin/export/current").then(r => { if (r.data.job) { setJob(r.data.job); poll(r.data.job.job_id); } }).catch(() => {});
    return () => clearTimeout(timer.current);
  }, []);

  const start = async () => {
    setBusy(true);
    try { const { data } = await api.post("/admin/export/start"); poll(data.job_id); }
    catch (e) { toast.error(e?.response?.data?.detail || "Could not start the export"); }
    finally { setBusy(false); }
  };

  const download = async () => {
    setBusy(true);
    try {
      const res = await api.get(`/admin/export/download/${job.job_id}`, { responseType: "blob" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(res.data); a.download = stampName(job.started_at); a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      toast.success("Export downloaded");
    } catch { toast.error("Download failed — the file may have expired. Start a new export."); }
    finally { setBusy(false); }
  };

  const running = job?.status === "running";
  return (
    <section className="border border-border bg-card max-w-2xl" data-testid="data-export-card">
      <div className="p-4 border-b border-border flex items-center gap-2">
        <Database size={16} weight="bold" className="text-primary"/>
        <span className="label-overline">Data Export</span>
      </div>
      <div className="p-5 space-y-4">
        <div className="flex gap-3 border border-[#FF3B30]/30 bg-[#FF3B30]/5 p-3 text-sm" data-testid="data-export-warning">
          <ShieldWarning size={20} weight="fill" className="text-[#FF3B30] shrink-0"/>
          <div>
            This file contains <b>all employee personal data</b> — bank details, IDs, attendance, photos and login password hashes.
            Store it securely and never share it. Use it only to move Kelasa to your own server.
          </div>
        </div>
        <p className="text-sm text-muted-foreground">
          Exports every database collection and every stored photo into one ZIP. The file is deleted from the server 1 hour after it's ready.
        </p>
        {job && (
          <div className="space-y-2" data-testid="data-export-progress">
            <div className="flex justify-between text-xs text-muted-foreground">
              <span data-testid="data-export-stage">{job.status === "failed" ? "Failed" : job.stage}</span>
              <span className="font-mono" data-testid="data-export-percent">{job.progress || 0}%</span>
            </div>
            <div className="h-2 bg-secondary overflow-hidden">
              <div className={`h-full transition-[width] duration-500 ${job.status === "failed" ? "bg-[#FF3B30]" : job.status === "done" ? "bg-[#00A152]" : "bg-primary"}`} style={{ width: `${job.progress || 0}%` }}/>
            </div>
            {job.status === "done" && job.manifest_summary && (
              <div className="text-xs text-muted-foreground font-mono" data-testid="data-export-summary">
                {job.manifest_summary.collections} collections · {job.manifest_summary.documents} records · {job.manifest_summary.photos} photos
                {job.manifest_summary.missing_photos ? ` · ${job.manifest_summary.missing_photos} missing` : ""} · {fmtSize(job.size_bytes)}
              </div>
            )}
            {job.status === "failed" && <div className="text-xs text-[#FF3B30]" data-testid="data-export-error">{job.error}</div>}
          </div>
        )}
        <div className="flex gap-2 flex-wrap">
          {job?.status === "done" ? (
            <>
              <button onClick={download} disabled={busy} data-testid="data-export-download"
                className="bg-[#00A152] text-white px-4 py-2.5 text-sm inline-flex items-center gap-2 disabled:opacity-50">
                <DownloadSimple size={16} weight="bold"/> Download ZIP
              </button>
              <button onClick={start} disabled={busy} data-testid="data-export-restart"
                className="border border-border px-4 py-2.5 text-sm inline-flex items-center gap-2 hover:bg-secondary">
                <ArrowClockwise size={14}/> New export
              </button>
            </>
          ) : (
            <button onClick={start} disabled={busy || running} data-testid="data-export-start"
              className="bg-foreground text-background px-4 py-2.5 text-sm inline-flex items-center gap-2 hover:bg-primary transition-colors disabled:opacity-50">
              <Database size={16} weight="bold"/> {running ? "Exporting…" : "Export all data"}
            </button>
          )}
        </div>
      </div>
    </section>
  );
};

export default function SettingsTab() {
  return <div className="space-y-6" data-testid="settings-tab"><DataExportCard/></div>;
}
