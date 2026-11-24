import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth";
import AppHeader from "@/components/AppHeader";
import AuthPhoto from "@/components/AuthPhoto";
import ProfileNudge from "@/components/ProfileNudge";
import CelebrationBanner from "@/components/CelebrationBanner";
import { Camera, Trash, Bank, IdentificationCard, CalendarHeart, Clock, CheckCircle, XCircle } from "@phosphor-icons/react";

const inputCls = "w-full bg-background border border-border px-3 py-2 text-sm";
const maxDate = new Date().toLocaleDateString("en-CA");

export const Field = ({ label, children, hint }) => (
  <div>
    <label className="label-overline mb-1.5 block">{label}</label>
    {children}
    {hint && <div className="text-[10px] text-muted-foreground mt-1">{hint}</div>}
  </div>
);

export const Section = ({ icon: Icon, title, children, testid, right }) => (
  <div className="border border-border bg-card" data-testid={testid}>
    <div className="p-4 border-b border-border flex items-center justify-between gap-2">
      <div className="flex items-center gap-2"><Icon size={16} weight="bold" className="text-primary"/><span className="label-overline">{title}</span></div>
      {right}
    </div>
    <div className="p-4 space-y-4">{children}</div>
  </div>
);

const resizeToJpeg = (file) => new Promise((resolve, reject) => {
  const img = new Image();
  img.onload = () => {
    const side = Math.min(img.width, img.height);
    const c = document.createElement("canvas");
    c.width = c.height = 512;
    c.getContext("2d").drawImage(img, (img.width - side) / 2, (img.height - side) / 2, side, side, 0, 0, 512, 512);
    URL.revokeObjectURL(img.src);
    resolve(c.toDataURL("image/jpeg", 0.85));
  };
  img.onerror = () => reject(new Error("Could not read that image"));
  img.src = URL.createObjectURL(file);
});

export default function ProfilePage() {
  const { user, setUser } = useAuth();
  const [p, setP] = useState(null);
  const load = () => api.get("/profile/me").then(r => setP(r.data)).catch(() => toast.error("Could not load profile"));
  useEffect(() => { load(); }, []);

  return (
    <div className="min-h-screen bg-background">
      <AppHeader/>
      <main className="max-w-[1100px] mx-auto px-4 sm:px-6 lg:px-8 py-8" data-testid="profile-page">
        <div className="label-overline">Employee</div>
        <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight mt-1">My Profile</h1>
        <CelebrationBanner/>
        <ProfileNudge profile={p} compact/>
        {!p ? <div className="mt-8 text-sm text-muted-foreground">Loading…</div> : (
          <div className="mt-8 grid lg:grid-cols-2 gap-6 items-start">
            <AvatarSection p={p} onChange={(path) => { setP({ ...p, avatar_path: path }); setUser({ ...user, avatar_path: path }); }}/>
            <DatesSection p={p} onSaved={setP}/>
            <StatutorySection key={p.esi_not_applicable ? "na" : "esi"} p={p} onSaved={setP}/>
            <BankSection p={p} reload={load}/>
          </div>
        )}
      </main>
    </div>
  );
}

function AvatarSection({ p, onChange }) {
  const ref = useRef(null);
  const [busy, setBusy] = useState(false);
  const pick = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!file.type.startsWith("image/")) return toast.error("Choose an image file");
    setBusy(true);
    try {
      const image_b64 = await resizeToJpeg(file);
      const { data } = await api.post("/profile/me/avatar", { image_b64 });
      onChange(data.avatar_path);
      toast.success("Profile photo updated");
    } catch (err) { toast.error(err?.response?.data?.detail || err.message || "Upload failed"); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    try { await api.delete("/profile/me/avatar"); onChange(null); toast.success("Photo removed"); }
    catch { toast.error("Could not remove"); }
  };
  return (
    <Section icon={Camera} title="Profile Photo" testid="profile-avatar-section">
      <div className="flex items-center gap-5">
        <AuthPhoto key={p.avatar_path || "none"} path={p.avatar_path} className="w-24 h-24 rounded-full object-cover border border-border"
          fallback={<div className="w-24 h-24 rounded-full bg-secondary grid place-items-center text-3xl font-semibold">{p.name?.[0]}</div>}/>
        <div className="space-y-2">
          <div className="text-sm font-medium" data-testid="profile-name">{p.name}</div>
          <div className="text-xs text-muted-foreground">{p.email}{p.site ? ` · ${p.site}` : ""}</div>
          <div className="flex gap-2">
            <input ref={ref} type="file" accept="image/*" className="hidden" onChange={pick} data-testid="profile-avatar-input"/>
            <button onClick={() => ref.current?.click()} disabled={busy} data-testid="profile-avatar-upload"
              className="bg-foreground text-background px-3 py-1.5 text-sm hover:bg-primary transition-colors disabled:opacity-50">
              {busy ? "Uploading…" : p.avatar_path ? "Change photo" : "Upload photo"}
            </button>
            {p.avatar_path && (
              <button onClick={remove} className="border border-border px-2 py-1.5 hover:text-[#FF3B30]" data-testid="profile-avatar-remove"><Trash size={14} weight="bold"/></button>
            )}
          </div>
        </div>
      </div>
    </Section>
  );
}

function useSaver(fields, p, onSaved) {
  const [f, setF] = useState(() => Object.fromEntries(fields.map(k => [k, p[k] || ""])));
  const [busy, setBusy] = useState(false);
  const dirty = fields.some(k => (p[k] || "") !== f[k]);
  const save = async () => {
    setBusy(true);
    try {
      const { data } = await api.put("/profile/me", f);
      setF(Object.fromEntries(fields.map(k => [k, data[k] || ""])));
      onSaved(data); toast.success("Saved");
    }
    catch (e) { toast.error(e?.response?.data?.detail || "Could not save"); }
    finally { setBusy(false); }
  };
  const bind = (k) => ({ value: f[k], onChange: (e) => setF({ ...f, [k]: e.target.value }) });
  return { bind, save, busy, dirty };
}

const SaveBtn = ({ s, testid }) => (
  <button onClick={s.save} disabled={s.busy || !s.dirty} data-testid={testid}
    className="bg-foreground text-background px-4 py-2 text-sm hover:bg-primary transition-colors disabled:opacity-40">Save</button>
);

function DatesSection({ p, onSaved }) {
  const s = useSaver(["dob", "wedding_anniversary", "date_of_joining"], p, onSaved);
  return (
    <Section icon={CalendarHeart} title="Special Dates" testid="profile-dates-section">
      <div className="grid sm:grid-cols-3 gap-3">
        <Field label="Date of Birth"><input type="date" max={maxDate} className={inputCls} {...s.bind("dob")} data-testid="profile-dob"/></Field>
        <Field label="Wedding Anniversary"><input type="date" max={maxDate} className={inputCls} {...s.bind("wedding_anniversary")} data-testid="profile-wedding"/></Field>
        <Field label="Joining Date"><input type="date" max={maxDate} className={inputCls} {...s.bind("date_of_joining")} data-testid="profile-joining"/></Field>
      </div>
      <p className="text-[11px] text-muted-foreground">Your team sees the day and month on the home screen celebrations — never your birth year.</p>
      <SaveBtn s={s} testid="profile-dates-save"/>
    </Section>
  );
}

function StatutorySection({ p, onSaved }) {
  const s = useSaver(["uan", "esi"], p, onSaved);
  return (
    <Section icon={IdentificationCard} title="EPF & ESI" testid="profile-statutory-section">
      <div className="grid sm:grid-cols-2 gap-3">
        <Field label="EPF UAN (optional)" hint="12 digits"><input inputMode="numeric" maxLength={14} className={`${inputCls} font-mono`} {...s.bind("uan")} placeholder="12-digit UAN" data-testid="profile-uan"/></Field>
        <Field label="ESI Number (optional)" hint={p.esi_not_applicable ? "Marked not applicable" : "10 or 17 digits"}>
          <input inputMode="numeric" maxLength={19} disabled={!!p.esi_not_applicable} className={`${inputCls} font-mono disabled:opacity-40`} {...s.bind("esi")}
            placeholder={p.esi_not_applicable ? "Not applicable" : "10 or 17 digits"} data-testid="profile-esi"/>
        </Field>
      </div>
      <label className="flex items-center gap-2 text-sm cursor-pointer" data-testid="profile-esi-na">
        <input type="checkbox" checked={!!p.esi_not_applicable} data-testid="profile-esi-na-checkbox" className="accent-[#0047FF]"
          onChange={async (e) => {
            const on = e.target.checked;
            try { const { data } = await api.put("/profile/me", { esi_not_applicable: on }); onSaved(data); toast.success(on ? "ESI marked not applicable" : "ESI required again"); }
            catch (err) { toast.error(err?.response?.data?.detail || "Could not save"); }
          }}/>
        ESI is not applicable to me
      </label>
      <p className="text-[11px] text-muted-foreground">Visible only to you, your branch sub-admin and admins.</p>
      <SaveBtn s={s} testid="profile-statutory-save"/>
    </Section>
  );
}

export const BankView = ({ bank }) => (
  <div className="grid grid-cols-2 gap-3 text-sm" data-testid="bank-current">
    <div><div className="label-overline mb-1">Account Holder</div>{bank.account_holder}</div>
    <div><div className="label-overline mb-1">Bank</div>{bank.bank_name || "—"}</div>
    <div><div className="label-overline mb-1">Account Number</div><span className="font-mono">{bank.account_number}</span></div>
    <div><div className="label-overline mb-1">IFSC</div><span className="font-mono">{bank.ifsc}</span></div>
  </div>
);

function BankSection({ p, reload }) {
  const [editing, setEditing] = useState(false);
  const [f, setF] = useState({ account_holder: p.name || "", account_number: "", confirm: "", ifsc: "", bank_name: "" });
  const [busy, setBusy] = useState(false);
  const pending = p.pending_bank;
  const last = p.last_bank_decision;

  const submit = async () => {
    if (f.account_number.replace(/\s/g, "") !== f.confirm.replace(/\s/g, "")) return toast.error("Account numbers don't match");
    setBusy(true);
    try {
      const { confirm, ...body } = f;
      await api.post("/profile/me/bank", body);
      toast.success("Sent to admin for approval");
      setEditing(false); reload();
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not submit"); }
    finally { setBusy(false); }
  };
  const cancel = async () => {
    try { await api.delete("/profile/me/bank"); toast.success("Request withdrawn"); reload(); }
    catch { toast.error("Could not withdraw"); }
  };
  const bind = (k, upper) => ({ value: f[k], onChange: (e) => setF({ ...f, [k]: upper ? e.target.value.toUpperCase() : e.target.value }) });

  return (
    <Section icon={Bank} title="Bank Account" testid="profile-bank-section"
      right={!editing && !pending && (
        <button onClick={() => setEditing(true)} className="text-[10px] label-overline hover:text-primary" data-testid="bank-edit-btn">
          {p.bank ? "REQUEST CHANGE" : "ADD DETAILS"}
        </button>
      )}>
      {p.bank ? <BankView bank={p.bank}/> : !pending && !editing && <div className="text-sm text-muted-foreground">No bank details yet.</div>}

      {pending && (
        <div className="border border-yellow-500/50 bg-yellow-500/5 p-3 text-sm" data-testid="bank-pending">
          <div className="flex items-center gap-2 font-medium"><Clock size={14} weight="bold" className="text-yellow-600"/> Waiting for admin approval</div>
          <div className="text-xs text-muted-foreground mt-1 font-mono">{pending.account_holder} · ••{pending.account_number.slice(-4)} · {pending.ifsc}</div>
          <button onClick={cancel} className="mt-2 text-[10px] label-overline hover:text-[#FF3B30]" data-testid="bank-withdraw-btn">WITHDRAW REQUEST</button>
        </div>
      )}
      {!pending && last && ["approved", "rejected"].includes(last.status) && (
        <div className="text-xs flex items-start gap-1.5" data-testid="bank-last-decision">
          {last.status === "approved" ? <CheckCircle size={14} weight="fill" className="text-[#00A86B]"/> : <XCircle size={14} weight="fill" className="text-[#FF3B30]"/>}
          <span>Last change ••{last.account_number.slice(-4)} was <strong>{last.status}</strong> by {last.decided_by}{last.note ? ` — "${last.note}"` : ""}</span>
        </div>
      )}

      {editing && (
        <div className="space-y-3 border-t border-border pt-4" data-testid="bank-form">
          <div className="grid sm:grid-cols-2 gap-3">
            <Field label="Account Holder Name"><input className={inputCls} {...bind("account_holder")} data-testid="bank-holder"/></Field>
            <Field label="Bank Name (optional)"><input className={inputCls} {...bind("bank_name")} data-testid="bank-name"/></Field>
            <Field label="Account Number"><input inputMode="numeric" className={`${inputCls} font-mono`} {...bind("account_number")} data-testid="bank-number"/></Field>
            <Field label="Confirm Account Number"><input inputMode="numeric" className={`${inputCls} font-mono`} {...bind("confirm")} data-testid="bank-number-confirm"/></Field>
            <Field label="IFSC Code" hint="e.g. SBIN0001234"><input maxLength={11} className={`${inputCls} font-mono`} {...bind("ifsc", true)} data-testid="bank-ifsc"/></Field>
          </div>
          <p className="text-[11px] text-muted-foreground">New bank details apply only after an admin approves them.</p>
          <div className="flex gap-2">
            <button onClick={submit} disabled={busy} data-testid="bank-submit-btn"
              className="bg-foreground text-background px-4 py-2 text-sm hover:bg-primary transition-colors disabled:opacity-50">Send for approval</button>
            <button onClick={() => setEditing(false)} className="border border-border px-4 py-2 text-sm hover:bg-secondary">Cancel</button>
          </div>
        </div>
      )}
    </Section>
  );
}
