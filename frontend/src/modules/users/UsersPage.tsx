import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Pencil, Plus, Unlock } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../../auth/context";
import { Card, ErrorState, Loading, PageHeader, Pill } from "../../components/ui";
import { Button, Field, FormError, Input, Modal, Select } from "../../components/ui/forms";
import { DataTable } from "../../components/ui/table";
import { api, send, type Role } from "../../lib/api";
import { fmtDate } from "../../lib/format";

interface User {
  id: number; username: string; full_name: string; email: string | null; role: Role; active: boolean;
  must_change_password: boolean; last_login_at: string | null; locked: boolean; personnel_id: number | null;
  open_sessions: number; created_at: string;
}
interface Roles { roles: { role: Role; permissions: string[] }[]; permissions: { key: string; description: string }[] }
interface Person { id: number; full_name: string; role: string }

const ROLES: Role[] = ["ADMIN", "ENGINEER", "TECHNICIAN", "QSSE", "VIEWER"];

function usePeople() {
  return useQuery({ queryKey: ["personnel"], queryFn: () => api<{ items: Person[] }>("/records/personnel", { limit: 500 }) });
}

function PersonSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { t } = useTranslation();
  const people = usePeople();
  return (
    <Select value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{t("users.noPersonnel")}</option>
      {people.data?.items.map((p) => <option key={p.id} value={p.id}>{p.full_name} — {p.role}</option>)}
    </Select>
  );
}

function CreateModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [f, setF] = useState({ username: "", full_name: "", email: "", role: "TECHNICIAN" as Role, password: "", personnel_id: "" });
  const mut = useMutation({
    mutationFn: () => send("POST", "/users", { ...f, email: f.email || null, personnel_id: f.personnel_id ? Number(f.personnel_id) : null }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["users"] }); onClose(); },
  });
  return (
    <Modal title={t("users.new")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button perm="users.manage" onClick={() => mut.mutate()} disabled={f.username.length < 3 || f.full_name.length < 3 || !f.password || mut.isPending}>{t("common.save")}</Button></>}>
      <div className="grid grid-cols-2 gap-3">
        <Field label={t("auth.username")}><Input value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} autoComplete="off" /></Field>
        <Field label={t("users.role")}>
          <Select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })}>
            {ROLES.map((r) => <option key={r} value={r}>{t(`roles.${r}`)}</option>)}
          </Select>
        </Field>
        <Field label={t("users.fullName")} className="col-span-2"><Input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
        <Field label={t("users.email")} className="col-span-2"><Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <Field label={t("users.personnel")} className="col-span-2" hint={t("users.personnelHint")}>
          <PersonSelect value={f.personnel_id} onChange={(v) => setF({ ...f, personnel_id: v })} />
        </Field>
        <Field label={t("users.tempPassword")} className="col-span-2" hint={t("users.tempPasswordHint")}>
          <Input type="password" autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
        </Field>
      </div>
      <div className="mt-3"><FormError error={mut.error} /></div>
    </Modal>
  );
}

function EditModal({ u, onClose }: { u: User; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { user: me } = useAuth();
  const self = me.id === u.id;
  const [f, setF] = useState({ full_name: u.full_name, email: u.email ?? "", role: u.role, active: u.active, personnel_id: u.personnel_id ? String(u.personnel_id) : "" });
  const [pwd, setPwd] = useState("");
  const inv = () => qc.invalidateQueries({ queryKey: ["users"] });
  const save = useMutation({
    mutationFn: () => send("PATCH", `/users/${u.id}`, {
      full_name: f.full_name, email: f.email || null, personnel_id: f.personnel_id ? Number(f.personnel_id) : null,
      ...(self ? {} : { role: f.role, active: f.active }),
    }),
    onSuccess: () => { inv(); onClose(); },
  });
  const unlock = useMutation({ mutationFn: () => send("PATCH", `/users/${u.id}`, { unlock: true }), onSuccess: inv });
  const reset = useMutation({ mutationFn: () => send("POST", `/users/${u.id}/reset-password`, { temporary_password: pwd }), onSuccess: () => { setPwd(""); inv(); } });
  const activity = useQuery({ queryKey: ["users", u.id, "activity"], queryFn: () => api<{ at: string; entity: string; entity_id: number; action: string }[]>(`/users/${u.id}/activity`) });
  return (
    <Modal wide title={`${u.username} — ${u.full_name}`} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button><Button perm="users.manage" onClick={() => save.mutate()} disabled={save.isPending}>{t("common.save")}</Button></>}>
      <div className="grid md:grid-cols-2 gap-5">
        <div className="space-y-3">
          <Field label={t("users.fullName")}><Input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
          <Field label={t("users.email")}><Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
          <Field label={t("users.role")} hint={self ? t("users.selfRole") : t("users.roleHint")}>
            <Select value={f.role} disabled={self} onChange={(e) => setF({ ...f, role: e.target.value as Role })}>
              {ROLES.map((r) => <option key={r} value={r}>{t(`roles.${r}`)}</option>)}
            </Select>
          </Field>
          <Field label={t("users.personnel")}><PersonSelect value={f.personnel_id} onChange={(v) => setF({ ...f, personnel_id: v })} /></Field>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={f.active} disabled={self} onChange={(e) => setF({ ...f, active: e.target.checked })} />
            {t("users.active")}
          </label>
          <FormError error={save.error} />
        </div>
        <div className="space-y-4">
          {u.locked && (
            <div className="rounded border border-warning/40 bg-warning/10 p-3 text-[13px]">
              <div className="mb-2">{t("users.lockedInfo")}</div>
              <Button perm="users.manage" variant="ghost" onClick={() => unlock.mutate()} disabled={unlock.isPending}><Unlock size={14} />{t("users.unlock")}</Button>
            </div>
          )}
          <div>
            <div className="text-xs text-fg-3 mb-1">{t("users.resetPassword")}</div>
            <div className="flex gap-2">
              <Input type="password" autoComplete="new-password" placeholder={t("users.tempPassword")} value={pwd} onChange={(e) => setPwd(e.target.value)} />
              <Button perm="users.manage" variant="ghost" onClick={() => reset.mutate()} disabled={!pwd || reset.isPending}><KeyRound size={14} />{t("users.reset")}</Button>
            </div>
            <div className="text-[11px] text-fg-3 mt-1">{reset.isSuccess ? t("users.resetDone") : t("users.resetHint")}</div>
            <div className="mt-2"><FormError error={reset.error} /></div>
          </div>
          <div>
            <div className="text-xs text-fg-3 mb-1">{t("users.activity")}</div>
            <div className="max-h-48 overflow-y-auto scroll-thin text-[12px] border border-line-soft rounded">
              {activity.data?.length === 0 && <div className="p-2 text-fg-3">—</div>}
              {activity.data?.map((a, i) => (
                <div key={i} className="px-2 py-1 border-b border-line-soft last:border-0 flex gap-2">
                  <span className="text-fg-3 tnum whitespace-nowrap">{a.at.slice(0, 16).replace("T", " ")}</span>
                  <span className="font-mono">{a.entity}{a.entity_id ? ` #${a.entity_id}` : ""}</span>
                  <span className="ml-auto text-fg-2">{a.action}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </Modal>
  );
}

export default function UsersPage() {
  const { t } = useTranslation();
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/users") });
  const roles = useQuery({ queryKey: ["users", "roles"], queryFn: () => api<Roles>("/auth/roles") });
  const [creating, setCreating] = useState(false);
  const [edit, setEdit] = useState<User | null>(null);

  return (
    <div>
      <PageHeader title={t("users.title")} subtitle={t("users.subtitle")}
        right={<Button perm="users.manage" onClick={() => setCreating(true)}><Plus size={14} />{t("users.new")}</Button>} />
      <div className="grid xl:grid-cols-3 gap-4">
        <Card title={t("users.accounts")} className="xl:col-span-2">
          {users.isPending ? <Loading /> : users.isError ? <ErrorState error={users.error} onRetry={() => users.refetch()} /> : (
            <DataTable rows={users.data} rowKey={(r) => r.id} onRowClick={setEdit} columns={[
              { key: "username", header: t("auth.username"), render: (r) => <span className="font-mono">{r.username}</span> },
              { key: "full_name", header: t("users.fullName") },
              { key: "role", header: t("users.role"), render: (r) => t(`roles.${r.role}`) },
              {
                key: "status", header: t("lab.status"), value: (r) => (r.active ? (r.locked ? 1 : 0) : 2), render: (r) =>
                  !r.active ? <Pill tone="neutral">{t("users.inactive")}</Pill>
                    : r.locked ? <Pill tone="warning">{t("users.locked")}</Pill>
                    : r.must_change_password ? <Pill tone="info">{t("users.pendingPassword")}</Pill>
                    : <Pill tone="good">{t("users.active")}</Pill>,
              },
              { key: "last_login_at", header: t("users.lastLogin"), render: (r) => (r.last_login_at ? fmtDate(r.last_login_at) : "—") },
              { key: "open_sessions", header: t("users.sessions"), align: "right" },
              { key: "edit", header: "", render: () => <Pencil size={14} className="text-fg-3" aria-hidden /> },
            ]} />
          )}
        </Card>
        <Card title={t("users.matrix")} subtitle={t("users.matrixHint")}>
          {roles.data && (
            <div className="overflow-x-auto">
              <table className="w-full text-[11.5px]">
                <thead>
                  <tr className="text-fg-3">
                    <th className="text-left font-normal py-1 pr-2">{t("users.permission")}</th>
                    {roles.data.roles.map((r) => <th key={r.role} className="font-normal px-1" title={t(`roles.${r.role}`)}>{r.role.slice(0, 3)}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {roles.data.permissions.map((p) => (
                    <tr key={p.key} className="border-t border-line-soft">
                      <td className="py-1 pr-2" title={p.description}>{t(`perm.${p.key}`, { defaultValue: p.description })}</td>
                      {roles.data.roles.map((r) => (
                        <td key={r.role} className="text-center">{r.permissions.includes(p.key) ? <span className="text-good" aria-label="yes">●</span> : <span className="text-fg-3" aria-label="no">·</span>}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
      {creating && <CreateModal onClose={() => setCreating(false)} />}
      {edit && <EditModal u={edit} onClose={() => setEdit(null)} />}
    </div>
  );
}
