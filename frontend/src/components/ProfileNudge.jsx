import { Link } from "react-router-dom";
import { CheckCircle, Circle, Clock, ArrowRight } from "@phosphor-icons/react";

export const profileChecklist = (p) => [
  { key: "bank", label: "Bank account", done: !!p.bank, waiting: !p.bank && !!p.pending_bank },
  { key: "uan", label: p.epf_not_applicable ? "EPF (not applicable)" : "EPF UAN (optional)", done: !!p.uan || !!p.epf_not_applicable, optional: true },
  { key: "esi", label: p.esi_not_applicable ? "ESI (not applicable)" : "ESI number (optional)", done: !!p.esi || !!p.esi_not_applicable, optional: true },
];

export default function ProfileNudge({ profile, compact = false }) {
  if (!profile) return null;
  const items = profileChecklist(profile);
  const required = items.filter(i => !i.optional);
  const score = required.reduce((s, i) => s + (i.done ? 1 : i.waiting ? 0.5 : 0), 0);
  const pct = Math.round((score / required.length) * 100);
  if (pct === 100) return null;

  return (
    <div className="mt-6 border border-[#0047FF]/40 bg-[#0047FF]/5 p-4" data-testid="profile-nudge">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="text-sm font-medium">Complete your payroll details</div>
          <div className="text-xs text-foreground/70">Your bank account is needed so salary is paid without delay. EPF and ESI are optional.</div>
        </div>
        <div className="font-mono text-2xl font-semibold text-primary" data-testid="profile-nudge-percent">{pct}%</div>
      </div>
      <div className="mt-3 h-2 bg-secondary overflow-hidden" data-testid="profile-nudge-bar">
        <div className="h-full bg-primary transition-[width] duration-700" style={{ width: `${pct}%` }}/>
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs">
        {items.map(i => (
          <span key={i.key} className={`inline-flex items-center gap-1 ${i.done ? "text-[#00A86B]" : i.waiting ? "text-yellow-700" : "text-muted-foreground"}`} data-testid={`profile-nudge-${i.key}`}>
            {i.done ? <CheckCircle size={13} weight="fill"/> : i.waiting ? <Clock size={13} weight="bold"/> : <Circle size={13} weight="bold"/>}
            {i.label}{i.waiting ? " · waiting approval" : ""}
          </span>
        ))}
      </div>
      {!compact && (
        <Link to="/profile" className="mt-3 inline-flex items-center gap-1.5 text-xs uppercase tracking-[0.15em] font-medium hover:text-primary" data-testid="profile-nudge-link">
          Finish profile <ArrowRight size={12} weight="bold"/>
        </Link>
      )}
    </div>
  );
}
