import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { ClockCounterClockwise } from "@phosphor-icons/react";

const LABELS = {
  employee_added: "Added employee",
  employee_removed: "Removed employee",
  employee_assigned: "Updated assignment",
  shift_updated: "Updated shift",
  role_changed: "Changed access level",
  scope_updated: "Updated sub-admin coverage",
  leave_approved: "Approved leave",
  leave_rejected: "Rejected leave",
  leave_type_added: "Added leave type",
  password_set: "Set a password",
  leave_cancelled: "Cancelled leave",
  leave_type_updated: "Updated leave type",
  leave_type_removed: "Retired leave type",
  holiday_added: "Added holiday",
  holiday_removed: "Removed holiday",
  announcement_posted: "Posted notice",
  announcement_removed: "Removed notice",
  department_added: "Added department",
  department_removed: "Removed department",
  site_added: "Added branch",
  site_removed: "Removed branch",
  branch_updated: "Updated branch geofence",
  field_staff_changed: "Changed field staff",
};

export default function ActivityTab() {
  const [entries, setEntries] = useState([]);

  useEffect(() => {
    api.get("/admin/activity").then(r => setEntries(r.data.entries || [])).catch(() => toast.error("Failed to load activity"));
  }, []);

  return (
    <div className="border border-border bg-card max-w-3xl" data-testid="activity-tab">
      <div className="p-4 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ClockCounterClockwise size={16} weight="bold" className="text-primary"/>
          <span className="label-overline">Admin Activity</span>
        </div>
        <span className="font-mono text-xs text-muted-foreground">{entries.length} EVENTS</span>
      </div>
      <div className="divide-y divide-border max-h-[640px] overflow-y-auto" data-testid="activity-list">
        {entries.map(e => (
          <div key={e.log_id} className="p-4 flex items-start gap-3" data-testid={`activity-${e.log_id}`}>
            <div className="font-mono text-[10px] text-muted-foreground w-32 shrink-0 pt-0.5">
              {new Date(e.created_at).toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm">
                <span className="font-medium">{e.actor_name}</span>
                <span className="text-muted-foreground"> · {LABELS[e.action] || e.action}</span>
                {e.target_name && <span className="font-medium"> → {e.target_name}</span>}
              </div>
              {e.details && <div className="text-[11px] font-mono text-muted-foreground mt-0.5 break-words">{e.details}</div>}
            </div>
          </div>
        ))}
        {entries.length === 0 && <div className="p-8 text-sm text-muted-foreground text-center">Nothing logged yet.</div>}
      </div>
    </div>
  );
}
