import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import AuthPhoto from "@/components/AuthPhoto";
import { AirplaneTilt } from "@phosphor-icons/react";

export default function AbsentToday({ heading = "Absent today" }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    api.get("/absent-today").then(r => setData(r.data)).catch(() => setData({ branches: [] }));
  }, []);

  const branches = data?.branches || [];
  const count = branches.reduce((n, b) => n + (b.people || []).length, 0);

  return (
    <section className="border border-border bg-card" data-testid="absent-today">
      <div className="p-4 border-b border-border flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <AirplaneTilt size={16} weight="bold" className="text-primary"/>
          <span className="label-overline">{heading}</span>
        </div>
        <span className="font-mono text-xs text-muted-foreground" data-testid="absent-today-count">{data ? count : "—"}</span>
      </div>
      {!data ? <div className="p-4 text-sm text-muted-foreground">Loading…</div>
        : count === 0 ? <div className="p-4 text-sm text-muted-foreground" data-testid="absent-today-empty">Nobody on approved leave.</div>
        : (
          <div className="divide-y divide-border">
            {branches.map(group => (
              <div key={group.branch} className="p-4" data-testid={`absent-branch-${group.branch}`}>
                <div className="text-[11px] uppercase tracking-wide text-muted-foreground mb-2">{group.branch}</div>
                <ul className="space-y-2">
                  {(group.people || []).map(person => (
                    <li key={`${group.branch}-${person.name}`} className="flex items-center gap-2 text-sm" data-testid="absent-person">
                      <AuthPhoto path={person.photo_path} alt="" className="w-7 h-7 object-cover bg-secondary"
                        fallback={<span className="w-7 h-7 bg-secondary inline-block"/>}/>
                      <span className="font-medium">{person.name}</span>
                      {person.designation && <span className="text-xs text-muted-foreground">{person.designation}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
    </section>
  );
}
