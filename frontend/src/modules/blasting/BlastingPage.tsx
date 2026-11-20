import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { AlertTriangle, ArrowRight, Check, CheckCircle2, Circle, Lock, ShieldAlert, Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams, useNavigate } from "react-router-dom";
import { Card, Empty, Loading, PageHeader, Pill, Progress, StatusPill } from "../../components/ui";
import { Button, Field, FormError, Input, Modal, Select, Textarea } from "../../components/ui/forms";
import { Tabs } from "../../components/ui/table";
import { api, ApiError, send } from "../../lib/api";
import { fmtDate, fmtNum, label } from "../../lib/format";
import { DeleteBlastButton, NewBlastModal } from "../operations/forms";
import { AttachmentsButton, AttachmentsPanel, useAttachmentCounts } from "../../components/Attachments";

interface BoardItem { id: number; code: string; status: string; planned_date: string; bench: string; work_order: string; approved_plan_ref: string; authorization_ref: string | null; checkpoints_done: number; checkpoints_total: number; next_status: string | null; blocked: boolean | null }
interface Detail {
  id: number; code: string; status: string; flow: string[]; next_status: string | null; next_requirements: string[]; planned_date: string; fired_at: string | null;
  bench: string; pattern: string; pattern_id: number; work_order: { code: string; title: string; status: string; engineering_forecast_ref: string; forecast_tonnes: number; actual_tonnes: number | null };
  approved_plan_ref: string; supervisor: string; blaster: string; equipment: string; authorization: { ref: string | null; by: string | null; role: string | null; at: string | null };
  checkpoints: { id: number; stage: string; name: string; is_authorization: boolean; completed: boolean; completed_by: string | null; completed_at: string | null; evidence_ref: string | null }[];
  history: { from: string | null; to: string; at: string; by: string; note: string | null }[];
  inventory: { received: number; used: number; returned: number; balance: number; reconciled: boolean; unit: string; movements: { id: number; type: string; product: string; quantity: number; unit: string; at: string; by: string; document_ref: string }[] };
  pre_blast_inspection: { id: number; code: string; status: string; inspected_at: string | null; inspector: string | null; items: { id: number; seq: number; text: string; result: string | null; comment: string | null }[] } | null;
  drillholes: { holes: number; measured: number; out_of_tolerance: number }; surveys: { id: number; code: string; type: string; quality: string }[];
  vibration: { id: number; station: string; ppv_mm_s: number | null; compliance: string; quality: string }[];
  delays: { date: string; category: string; hours: number; description: string }[]; post_blast_review: { stage: string; due_date: string } | null; notice: string;
}

function errorList(e: unknown): string[] | null {
  if (e instanceof ApiError) {
    const d = e.detail as { unmet?: string[] } | undefined;
    if (d && typeof d === "object" && Array.isArray(d.unmet)) return d.unmet;
  }
  return null;
}

function TransitionModal({ d, onClose }: { d: Detail; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const auth = d.next_status === "AUTHORIZED";
  const [f, setF] = useState({ note: "", authorization_ref: "", authorized_by: "", authorized_role: "Blaster in charge" });
  const mut = useMutation({
    mutationFn: () => send("POST", `/blasts/${d.id}/transition`, { to_status: d.next_status, ...f, note: f.note || null }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["blasts"] }); onClose(); },
  });
  const unmet = errorList(mut.error);
  return (
    <Modal title={`${d.code}: ${label(d.status)} → ${label(d.next_status)}`} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button><Button perm={d.next_status === "CLOSED" ? "blast.close" : "blast.operate"} onClick={() => mut.mutate()} disabled={mut.isPending}>{t("bo.confirm")}</Button></>}>
      <div className="space-y-3">
        {auth && <div className="flex gap-2 rounded border border-warning/50 bg-warning/10 p-3 text-[13px]"><ShieldAlert size={18} className="text-warning shrink-0" /><span>{t("bo.authNotice")}</span></div>}
        {auth && (
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("bo.authRef")} className="col-span-2"><Input value={f.authorization_ref} onChange={(e) => setF({ ...f, authorization_ref: e.target.value })} placeholder="AUTH-…" /></Field>
            <Field label={t("bo.authBy")}><Input value={f.authorized_by} onChange={(e) => setF({ ...f, authorized_by: e.target.value })} /></Field>
            <Field label={t("bo.authRole")}><Input value={f.authorized_role} onChange={(e) => setF({ ...f, authorized_role: e.target.value })} /></Field>
          </div>
        )}
        <Field label={t("bo.note")}><Textarea value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></Field>
        {unmet ? <div className="rounded border border-critical/40 bg-critical/10 p-3 text-[13px]"><div className="font-medium mb-1">{t("bo.blockedBy")}</div><ul className="list-disc pl-5">{unmet.map((u) => <li key={u}>{u}</li>)}</ul></div> : <FormError error={mut.error} />}
      </div>
    </Modal>
  );
}

function CheckpointRow({ c, locked, files }: { c: Detail["checkpoints"][number]; locked: boolean; files?: number }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [ev, setEv] = useState("");
  const [open, setOpen] = useState(false);
  const mut = useMutation({ mutationFn: () => send("POST", `/checkpoints/${c.id}/complete`, { evidence_ref: ev }), onSuccess: () => qc.invalidateQueries({ queryKey: ["blasts"] }) });
  const auto = c.is_authorization;
  return (
    <li className="flex items-start gap-3 py-1.5 border-b border-line-soft last:border-0">
      {c.completed ? <CheckCircle2 size={16} className="text-good mt-0.5 shrink-0" /> : <Circle size={16} className="text-fg-3 mt-0.5 shrink-0" />}
      <div className="flex-1 min-w-0">
        <div className={clsx("text-[13px]", !c.completed && "text-fg-2")}>{c.name}</div>
        {c.completed && <div className="text-[11px] text-fg-3">{c.completed_by} · {c.completed_at?.slice(0, 16).replace("T", " ")} · <span className="font-mono">{c.evidence_ref}</span></div>}
        {auto && !c.completed && <div className="text-[11px] text-fg-3">{t("bo.autoAuth")}</div>}
        {open && <div className="flex gap-2 mt-1"><Input className="py-1 text-xs" placeholder={t("bo.evidence")} value={ev} onChange={(e) => setEv(e.target.value)} /><Button perm="blast.operate" className="py-1 text-xs" onClick={() => mut.mutate()} disabled={ev.length < 2}>{t("common.save")}</Button></div>}
        <FormError error={mut.error} />
      </div>
      <AttachmentsButton entity="blast_checkpoint" entityId={c.id} count={files} title={c.name} />
      {!c.completed && !auto && !locked && !open && <Button perm="blast.operate" variant="ghost" className="py-0.5 text-xs" onClick={() => setOpen(true)}><Check size={12} />{t("bo.markDone")}</Button>}
    </li>
  );
}

function Checklist({ insp, locked }: { insp: NonNullable<Detail["pre_blast_inspection"]>; locked: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const people = useQuery({ queryKey: ["personnel"], queryFn: () => api<{ items: { id: number; full_name: string; role: string }[] }>("/records/personnel", { limit: 200 }) });
  const [inspector, setInspector] = useState("1");
  const [comments, setComments] = useState<Record<number, string>>({});
  const setItem = useMutation({ mutationFn: (p: { id: number; result: string }) => send("PATCH", `/checklist-items/${p.id}`, { result: p.result, comment: comments[p.id] || null }), onSuccess: () => qc.invalidateQueries({ queryKey: ["blasts"] }) });
  const complete = useMutation({ mutationFn: () => send("POST", `/inspections/${insp.id}/complete`, { inspector_id: Number(inspector) }), onSuccess: () => qc.invalidateQueries({ queryKey: ["blasts"] }) });
  const done = insp.status === "COMPLETED";
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm"><span className="font-mono">{insp.code}</span><StatusPill status={done ? "COMPLETED" : "PLANNED"} text={label(insp.status)} />
        {done && <span className="text-fg-3 text-xs">{insp.inspector} · {insp.inspected_at?.slice(0, 16).replace("T", " ")}</span>}</div>
      <p className="text-[11.5px] text-fg-3">{t("bo.checklistNote")}</p>
      <ul>
        {insp.items.map((i) => (
          <li key={i.id} className="flex flex-wrap items-center gap-2 py-1.5 border-b border-line-soft">
            <span className="text-fg-3 tnum w-5">{i.seq}.</span><span className="flex-1 text-[13px] min-w-[16rem]">{i.text}</span>
            {done || locked ? <span className="text-xs">{i.result ? label(i.result) : "—"}{i.comment && <span className="text-fg-3"> · {i.comment}</span>}</span> : (
              <>
                <Input className="py-0.5 text-xs w-44" placeholder={t("bo.comment")} value={comments[i.id] ?? i.comment ?? ""} onChange={(e) => setComments({ ...comments, [i.id]: e.target.value })} />
                {["YES", "NO", "NA"].map((r) => (
                  <button key={r} onClick={() => setItem.mutate({ id: i.id, result: r })} aria-pressed={i.result === r}
                    className={clsx("px-2 py-0.5 rounded border text-xs", i.result === r ? (r === "NO" ? "bg-critical text-white border-critical" : "bg-accent text-ink-950 border-accent") : "border-line text-fg-2")}>{r}</button>
                ))}
              </>
            )}
          </li>
        ))}
      </ul>
      <FormError error={setItem.error} />
      {!done && !locked && (
        <div className="flex items-end gap-2">
          <Field label={t("bo.inspector")}><Select value={inspector} onChange={(e) => setInspector(e.target.value)}>{people.data?.items.map((p) => <option key={p.id} value={p.id}>{p.full_name} — {p.role}</option>)}</Select></Field>
          <Button perm="blast.operate" onClick={() => complete.mutate()} disabled={complete.isPending}>{t("bo.completeChecklist")}</Button>
        </div>
      )}
      <FormError error={complete.error} />
    </div>
  );
}

function Inventory({ d }: { d: Detail }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const lastProduct = d.inventory.movements.length ? d.inventory.movements[d.inventory.movements.length - 1].product : "";
  const [f, setF] = useState({ movement_type: d.inventory.movements.length ? "RETURNED" : "RECEIVED", quantity: "", document_ref: "", product_name: lastProduct ?? "" });
  const mut = useMutation({ mutationFn: () => send("POST", `/blasts/${d.id}/inventory`, { ...f, quantity: Number(f.quantity), product_name: f.product_name || null }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["blasts"] }); setF({ ...f, quantity: "", document_ref: "" }); } });
  const inv = d.inventory;
  const locked = ["COMPLETED", "CLOSED"].includes(d.status);
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-4 gap-2 text-center tnum">
        {[["RECEIVED", inv.received], ["USED", inv.used], ["RETURNED", inv.returned]].map(([k, v]) => <div key={k as string} className="rounded border border-line-soft p-2"><div className="text-[11px] text-fg-3">{label(k as string)}</div><div className="text-lg font-semibold">{fmtNum(v as number, 2)} {inv.unit}</div></div>)}
        <div className={clsx("rounded border p-2", inv.reconciled ? "border-good/50" : "border-warning/60")}><div className="text-[11px] text-fg-3">{t("bo.balance")}</div><div className="text-lg font-semibold">{fmtNum(inv.balance, 3)} {inv.unit}</div>
          {inv.reconciled ? <Pill tone="good">{t("bo.reconciled")}</Pill> : <Pill tone="warning">{t("bo.notReconciled")}</Pill>}</div>
      </div>
      <table className="w-full text-[12.5px] tnum">
        <thead className="text-[11px] uppercase text-fg-3"><tr className="border-b border-line-soft"><th className="text-left py-1">{t("bo.movement")}</th><th className="text-left">{t("bo.product")}</th><th className="text-right">{t("bo.qty")}</th><th className="text-left pl-3">{t("bo.doc")}</th><th className="text-left">{t("bo.by")}</th><th className="text-left">{t("lab.date")}</th></tr></thead>
        <tbody>{inv.movements.map((x) => <tr key={x.id} className="border-b border-line-soft"><td className="py-1">{label(x.type)}</td><td className="text-fg-2">{x.product}</td><td className="text-right">{fmtNum(x.quantity, 3)} {x.unit}</td><td className="pl-3 font-mono">{x.document_ref}</td><td>{x.by}</td><td>{x.at.slice(0, 16).replace("T", " ")}</td></tr>)}</tbody>
      </table>
      {!locked && (
        <div className="flex flex-wrap items-end gap-2">
          <Field label={t("bo.movement")}><Select value={f.movement_type} onChange={(e) => setF({ ...f, movement_type: e.target.value })}>{["RECEIVED", "USED", "RETURNED"].map((x) => <option key={x} value={x}>{label(x)}</option>)}</Select></Field>
          <Field label={t("bo.product")}><Input value={f.product_name} onChange={(e) => setF({ ...f, product_name: e.target.value })} className="w-56" /></Field>
          <Field label={`${t("bo.qty")} (t)`}><Input type="number" step="0.001" min="0" value={f.quantity} onChange={(e) => setF({ ...f, quantity: e.target.value })} className="w-28" /></Field>
          <Field label={t("bo.doc")}><Input value={f.document_ref} onChange={(e) => setF({ ...f, document_ref: e.target.value })} className="w-40" /></Field>
          <Button perm="blast.operate" onClick={() => mut.mutate()} disabled={!f.quantity || f.document_ref.length < 2 || f.product_name.trim().length < 2 || mut.isPending}>{t("bo.addMovement")}</Button>
        </div>
      )}
      <p className="text-[11px] text-fg-3">{t("bo.inventoryNote")}</p>
      <FormError error={mut.error} />
    </div>
  );
}

function BlastDetail({ id }: { id: number }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [tab, setTab] = useState<"checkpoints" | "checklist" | "inventory" | "records" | "evidence" | "history">("checkpoints");
  const [trans, setTrans] = useState(false);
  const q = useQuery({ queryKey: ["blasts", id], queryFn: () => api<Detail>(`/blasts/${id}`) });
  const d = q.data;
  const cpFiles = useAttachmentCounts("blast_checkpoint", d?.checkpoints.map((c) => c.id) ?? []);
  if (!d) return <Loading />;
  const idx = d.flow.indexOf(d.status);
  const locked = d.status === "CLOSED";
  const stages = ["PREPARATION", "LOADING", "PRE_BLAST", "POST_BLAST"];
  return (
    <Card>
      <div className="flex flex-wrap justify-between gap-3">
        <div>
          <div className="flex items-center gap-2"><h2 className="text-lg font-semibold font-mono">{d.code}</h2><StatusPill status={d.status} /></div>
          <div className="text-xs text-fg-3 mt-1">{d.bench} · {fmtDate(d.planned_date)} · {d.work_order.code} · {t("bo.plan")}: <span className="font-mono text-fg-2">{d.approved_plan_ref}</span> · {t("bo.supervisor")}: {d.supervisor} · {t("bo.blaster")}: {d.blaster} · {t("bo.equipment")}: {d.equipment}</div>
          {d.authorization.ref && <div className="text-xs text-fg-3 mt-0.5">{t("dashboard.authRef")}: <span className="font-mono text-fg-2">{d.authorization.ref}</span> · {d.authorization.by} ({d.authorization.role}) · {d.authorization.at?.slice(0, 16).replace("T", " ")}</div>}
        </div>
        <div className="flex flex-col items-end gap-2 self-start">
          <Link to={`/drillholes?pattern=${d.pattern_id}`} className="text-xs text-accent hover:underline">{d.pattern} →</Link>
          {d.status === "PLANNED" && <DeleteBlastButton id={d.id} onDeleted={() => navigate("/blasting")} />}
        </div>
      </div>
      <ol className="flex flex-wrap gap-1 mt-4" aria-label="workflow">
        {d.flow.map((s, i) => (
          <li key={s} className={clsx("flex-1 min-w-[7rem] rounded px-2 py-1.5 text-[11px] border", i < idx ? "border-good/40 text-good bg-good/5" : i === idx ? "border-accent bg-accent-soft text-fg font-semibold" : "border-line text-fg-3")}>
            <span className="tnum mr-1">{i + 1}.</span>{label(s)}
          </li>
        ))}
      </ol>
      {d.next_status && (
        <div className={clsx("mt-3 rounded border p-3 flex flex-wrap items-start gap-3", d.next_requirements.length ? "border-warning/50 bg-warning/5" : "border-good/40 bg-good/5")}>
          <div className="flex-1 min-w-[16rem]">
            <div className="text-sm font-medium">{t("bo.nextStep")}: {label(d.next_status)}</div>
            {d.next_requirements.length ? (
              <ul className="mt-1 text-[12.5px] text-fg-2 space-y-0.5">{d.next_requirements.map((r) => <li key={r} className="flex gap-1.5"><AlertTriangle size={13} className="text-warning shrink-0 mt-0.5" />{r}</li>)}</ul>
            ) : <div className="text-[12.5px] text-good mt-1">{t("bo.ready")}</div>}
          </div>
          <Button perm={d.next_status === "CLOSED" ? "blast.close" : "blast.operate"} onClick={() => setTrans(true)} disabled={d.next_requirements.length > 0}><ArrowRight size={14} />{t("bo.advance")}</Button>
        </div>
      )}
      {locked && <div className="mt-3 text-xs text-fg-3 flex items-center gap-1.5"><Lock size={12} />{t("bo.closedNote")}</div>}
      <div className="mt-4">
        <Tabs value={tab} onChange={setTab} tabs={[
          { v: "checkpoints", l: `${t("bo.checkpoints")} (${d.checkpoints.filter((c) => c.completed).length}/${d.checkpoints.length})` },
          { v: "checklist", l: t("bo.checklist") }, { v: "inventory", l: t("bo.inventory") }, { v: "records", l: t("bo.records") }, { v: "evidence", l: t("att.title") }, { v: "history", l: t("bo.history") },
        ]} />
        {tab === "checkpoints" && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {stages.map((s) => (
              <div key={s}><h3 className="text-xs uppercase tracking-wide text-fg-3 mb-1">{label(s)}</h3>
                <ul>{d.checkpoints.filter((c) => c.stage === s).map((c) => <CheckpointRow key={c.id} c={c} locked={locked} files={cpFiles.data?.[String(c.id)]} />)}</ul></div>
            ))}
          </div>
        )}
        {tab === "checklist" && (d.pre_blast_inspection ? <><Checklist insp={d.pre_blast_inspection} locked={locked} />
          <div className="mt-4"><AttachmentsPanel entity="inspection" entityId={d.pre_blast_inspection.id} /></div></> : <Empty>{t("common.none")}</Empty>)}
        {tab === "evidence" && <AttachmentsPanel entity="blast" entityId={d.id} />}
        {tab === "inventory" && <Inventory d={d} />}
        {tab === "records" && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-[12.5px]">
            <div><h3 className="text-xs uppercase text-fg-3 mb-1">{t("nav.drillholes")}</h3>{d.drillholes.measured}/{d.drillholes.holes} {t("bo.measured")} · {d.drillholes.out_of_tolerance} {t("dashboard.outOfTol")}</div>
            <div><h3 className="text-xs uppercase text-fg-3 mb-1">{t("nav.scanning")}</h3>{d.surveys.length ? d.surveys.map((s) => <div key={s.id}><Link className="font-mono text-accent hover:underline" to={`/scanning?survey=${s.id}`}>{s.code}</Link> · {label(s.type)} · {label(s.quality)}</div>) : t("common.none")}</div>
            <div><h3 className="text-xs uppercase text-fg-3 mb-1">{t("nav.vibration")}</h3>{d.vibration.length ? d.vibration.map((v) => <div key={v.id}>{v.station}: {fmtNum(v.ppv_mm_s, 2)} mm/s · {label(v.compliance)}</div>) : t("common.none")}</div>
            <div><h3 className="text-xs uppercase text-fg-3 mb-1">{t("bo.delays")}</h3>{d.delays.length ? d.delays.map((x, i) => <div key={i}>{x.date} · {label(x.category)} · {x.hours} h — {x.description}</div>) : t("common.none")}</div>
            <div><h3 className="text-xs uppercase text-fg-3 mb-1">{t("nav.postblast")}</h3>{d.post_blast_review ? `${label(d.post_blast_review.stage)} · ${t("dh.due")} ${d.post_blast_review.due_date}` : t("common.none")}</div>
            <div><h3 className="text-xs uppercase text-fg-3 mb-1">{t("bo.production")}</h3>{t("bo.forecast")} {fmtNum(d.work_order.forecast_tonnes, 0)} t · {t("bo.actual")} {d.work_order.actual_tonnes ? `${fmtNum(d.work_order.actual_tonnes, 0)} t` : "—"} · <span className="font-mono">{d.work_order.engineering_forecast_ref}</span></div>
          </div>
        )}
        {tab === "history" && (
          <ol className="relative border-l border-line ml-2">
            {d.history.map((h, i) => (
              <li key={i} className="ml-4 pb-3"><span className="absolute -left-1.5 w-3 h-3 rounded-full bg-accent mt-1" />
                <div className="text-[13px]">{h.from ? `${label(h.from)} → ` : ""}<strong>{label(h.to)}</strong></div>
                <div className="text-[11px] text-fg-3">{h.at.slice(0, 16).replace("T", " ")} · {h.by}</div>{h.note && <div className="text-[12px] text-fg-2">{h.note}</div>}</li>
            ))}
          </ol>
        )}
      </div>
      <p className="text-[11px] text-fg-3 mt-4">{d.notice}</p>
      {trans && <TransitionModal d={d} onClose={() => setTrans(false)} />}
    </Card>
  );
}

export default function BlastingPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const q = useQuery({ queryKey: ["blasts", "board"], queryFn: () => api<{ flow: string[]; blasts: BoardItem[] }>("/blasts") });
  const sel = Number(params.get("blast")) || q.data?.blasts.find((b) => b.status === "AUTHORIZED")?.id;
  const [creating, setCreating] = useState(false);
  return (
    <div className="space-y-4">
      <PageHeader title={t("bo.title")} subtitle={t("bo.subtitle")}
        right={<Button perm="planning.write" onClick={() => setCreating(true)}><Plus size={14} />{t("ops.newBlast")}</Button>} />
      {creating && <NewBlastModal onClose={() => setCreating(false)} onCreated={(id) => { setCreating(false); setParams({ blast: String(id) }); }} />}
      {q.isLoading && <Loading />}
      {q.data && (
        <div className="flex gap-3 overflow-x-auto scroll-thin pb-2">
          {q.data.flow.map((s) => {
            const items = q.data.blasts.filter((b) => b.status === s);
            const shown = s === "CLOSED" ? items.slice(0, 4) : items;
            return (
              <div key={s} className="min-w-[13.5rem] flex-1 rounded-lg border border-line bg-ink-900">
                <div className="px-3 py-2 border-b border-line flex justify-between text-[11px] uppercase tracking-wide text-fg-3"><span>{label(s)}</span><span className="tnum">{items.length}</span></div>
                <div className="p-2 space-y-2">
                  {shown.length === 0 && <div className="text-[11px] text-fg-3 text-center py-2">—</div>}
                  {shown.map((b) => (
                    <button key={b.id} onClick={() => setParams({ blast: String(b.id) })}
                      className={clsx("w-full text-left rounded border bg-ink-800 p-2 hover:border-accent/60", b.id === sel ? "border-accent" : "border-line")}>
                      <div className="flex justify-between"><span className="font-mono text-[12px]">{b.code}</span><span className="text-[11px] text-fg-3">{fmtDate(b.planned_date)}</span></div>
                      <div className="text-[11px] text-fg-3">{b.bench} · {b.work_order}</div>
                      <div className="flex items-center gap-2 mt-1"><Progress value={b.checkpoints_done} max={b.checkpoints_total} tone={b.checkpoints_done === b.checkpoints_total ? "good" : "info"} /><span className="text-[10.5px] tnum text-fg-3">{b.checkpoints_done}/{b.checkpoints_total}</span></div>
                      {b.blocked && <div className="text-[10.5px] text-warning mt-0.5 flex items-center gap-1"><AlertTriangle size={11} />{t("bo.blocked")}</div>}
                    </button>
                  ))}
                  {items.length > shown.length && <div className="text-[11px] text-fg-3 text-center">+{items.length - shown.length}</div>}
                </div>
              </div>
            );
          })}
        </div>
      )}
      {sel && <BlastDetail key={sel} id={sel} />}
    </div>
  );
}
