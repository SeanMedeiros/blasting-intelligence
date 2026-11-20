import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronLeft, ChevronRight, PackageCheck, Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { axisProps, chart } from "../../components/charts/theme";
import { Card, Loading, PageHeader, Pill, StatusPill } from "../../components/ui";
import { Button, Field, FormError, Input, Modal, Select, Textarea } from "../../components/ui/forms";
import { DataTable, Tabs } from "../../components/ui/table";
import { api, send } from "../../lib/api";
import { fmtDate, fmtNum, label } from "../../lib/format";
import { addDays, useToday, weekStart } from "../../lib/dates";
import { NewDeliveryModal, NewWorkOrderModal, WorkOrderModal } from "../operations/forms";

interface Item { id: number; work_order: string; blast: string | null; bench: string | null; activity: string; planned_date: string; actual_date: string | null; status: string; resources: string | null; responsible: string | null; changes: number; late: boolean }
interface Schedule { start: string; end: string; today: string; items: Item[]; gantt: { work_order: string; blast: string | null; bench: string | null; items: Item[] }[] }
const CAUSES = ["WEATHER", "EQUIPMENT", "PRODUCT_SUPPLY", "CLIENT_ACCESS", "REDRILL", "AUTHORIZATION_WAIT", "WILDLIFE_EXCLUSION", "OTHER"];
const ACT_ABBR: Record<string, string> = { DRILLING: "DR", FACE_SURVEY: "3D", HOLE_VERIFICATION: "HV", LOADING: "LD", BLAST: "BL", POST_BLAST_SURVEY: "PS", POST_BLAST_REVIEW: "PR" };
const STATUS_BG: Record<string, string> = { DONE: "bg-good/20 border-good/50", DELAYED: "bg-critical/20 border-critical/60", IN_PROGRESS: "bg-series-1/25 border-series-1/60", PLANNED: "bg-ink-700 border-line" };


function ItemModal({ it, onClose }: { it: Item; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const today = useToday();
  const [f, setF] = useState({ new_date: addDays(it.planned_date < today ? today : it.planned_date, 1), cause_category: "WEATHER", cause: "", delay_hours: "" });
  const [actual, setActual] = useState(today);
  const inv = () => { qc.invalidateQueries({ queryKey: ["plan"] }); onClose(); };
  const resched = useMutation({ mutationFn: () => send("POST", `/planning/items/${it.id}/reschedule`, { ...f, delay_hours: f.delay_hours ? +f.delay_hours : null }), onSuccess: inv });
  const done = useMutation({ mutationFn: () => send("POST", `/planning/items/${it.id}/complete`, { actual_date: actual }), onSuccess: inv });
  return (
    <Modal title={`${label(it.activity)} — ${it.work_order}`} onClose={onClose} wide>
      <div className="space-y-4">
        <div className="text-[13px] text-fg-2">{it.blast} · {it.bench} · {t("plan.planned")} {it.planned_date} · {it.responsible} · {it.resources} · <StatusPill status={it.status} /></div>
        {it.status !== "DONE" && (
          <>
            <div className="rounded border border-line-soft p-3 space-y-3">
              <div className="text-xs uppercase text-fg-3">{t("plan.reschedule")}</div>
              <div className="grid grid-cols-3 gap-3">
                <Field label={t("plan.newDate")}><Input type="date" value={f.new_date} onChange={(e) => setF({ ...f, new_date: e.target.value })} /></Field>
                <Field label={t("plan.cause")}><Select value={f.cause_category} onChange={(e) => setF({ ...f, cause_category: e.target.value })}>{CAUSES.map((c) => <option key={c} value={c}>{label(c)}</option>)}</Select></Field>
                <Field label={t("plan.delayHours")}><Input type="number" min="0" value={f.delay_hours} onChange={(e) => setF({ ...f, delay_hours: e.target.value })} /></Field>
              </div>
              <Field label={t("plan.causeDetail")}><Textarea rows={2} value={f.cause} onChange={(e) => setF({ ...f, cause: e.target.value })} /></Field>
              <Button perm="planning.write" onClick={() => resched.mutate()} disabled={f.cause.length < 5}>{t("plan.saveChange")}</Button>
              <FormError error={resched.error} />
            </div>
            {it.activity !== "BLAST" ? (
              <div className="flex items-end gap-2"><Field label={t("plan.actualDate")}><Input type="date" value={actual} onChange={(e) => setActual(e.target.value)} /></Field><Button perm="planning.write" variant="ghost" onClick={() => done.mutate()}>{t("plan.markDone")}</Button></div>
            ) : <p className="text-[12px] text-fg-3">{t("plan.blastViaWorkflow")}</p>}
            <FormError error={done.error} />
          </>
        )}
      </div>
    </Modal>
  );
}

function ReceiveModal({ d, onClose }: { d: { id: number; code: string; planned_qty: number }; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const today = useToday();
  const [f, setF] = useState({ actual_date: today, delivered_qty: String(d.planned_qty), document_ref: "" });
  const mut = useMutation({ mutationFn: () => send("POST", `/planning/deliveries/${d.id}/receive`, { ...f, delivered_qty: +f.delivered_qty }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["plan"] }); onClose(); } });
  return (
    <Modal title={`${t("plan.receive")} — ${d.code}`} onClose={onClose} footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button><Button perm="planning.write" onClick={() => mut.mutate()} disabled={f.document_ref.length < 2}>{t("common.save")}</Button></>}>
      <div className="grid grid-cols-3 gap-3">
        <Field label={t("plan.actualDate")}><Input type="date" value={f.actual_date} onChange={(e) => setF({ ...f, actual_date: e.target.value })} /></Field>
        <Field label={t("plan.qty")}><Input type="number" step="0.1" value={f.delivered_qty} onChange={(e) => setF({ ...f, delivered_qty: e.target.value })} /></Field>
        <Field label={t("bo.doc")}><Input value={f.document_ref} onChange={(e) => setF({ ...f, document_ref: e.target.value })} placeholder="BOL-…" /></Field>
      </div>
      <div className="mt-2"><FormError error={mut.error} /></div>
    </Modal>
  );
}

export default function PlanningPage() {
  const { t } = useTranslation();
  const today = useToday();
  const [start, setStart] = useState(weekStart(today));
  const [tab, setTab] = useState<"calendar" | "gantt">("calendar");
  const [sel, setSel] = useState<Item | null>(null);
  const [recv, setRecv] = useState<{ id: number; code: string; planned_qty: number } | null>(null);
  const [creating, setCreating] = useState<"" | "wo" | "delivery">("");
  const [woSel, setWoSel] = useState<{ id: number; code: string; title: string; status: string } | null>(null);
  const end = addDays(start, 13);
  const sched = useQuery({ queryKey: ["plan", "schedule", start], queryFn: () => api<Schedule>("/planning/schedule", { start, end }) });
  const wos = useQuery({ queryKey: ["plan", "wo"], queryFn: () => api<{ id: number; code: string; title: string; area: string; status: string; engineering_forecast_ref: string; planned_start: string; forecast_tonnes: number; actual_tonnes: number | null; tonnes_variance_pct: number | null; progress_pct: number }[]>("/planning/work-orders") });
  const prod = useQuery({ queryKey: ["plan", "prod"], queryFn: () => api<{ week: string; forecast_t: number; actual_t: number | null }[]>("/planning/production") });
  const dl = useQuery({ queryKey: ["plan", "deliveries"], queryFn: () => api<{ id: number; code: string; product: string; area: string; planned_date: string; actual_date: string | null; planned_qty: number; delivered_qty: number | null; status: string; document_ref: string | null }[]>("/planning/deliveries") });
  const delays = useQuery({ queryKey: ["plan", "delays"], queryFn: () => api<{ pareto: { category: string; events: number; hours: number }[]; changes: { id: number; at: string; work_order: string; activity: string; old_date: string; new_date: string; cause_category: string; cause: string; by: string }[] }>("/planning/delays") });
  const days = Array.from({ length: 14 }, (_, i) => addDays(start, i));
  const s = sched.data;

  return (
    <div className="space-y-4">
      <PageHeader title={t("plan.title")} subtitle={t("plan.subtitle")} right={
        <div className="flex gap-2">
          <Button perm="planning.write" onClick={() => setCreating("wo")}><Plus size={14} />{t("ops.newWorkOrder")}</Button>
          <Button perm="planning.write" variant="ghost" onClick={() => setCreating("delivery")}><Plus size={14} />{t("ops.newDelivery")}</Button>
        </div>} />
      {creating === "wo" && <NewWorkOrderModal onClose={() => setCreating("")} />}
      {creating === "delivery" && <NewDeliveryModal onClose={() => setCreating("")} />}
      {woSel && <WorkOrderModal wo={woSel} onClose={() => setWoSel(null)} />}
      <Card bodyClass="p-3" title={`${fmtDate(start)} – ${fmtDate(end)}`} actions={
        <div className="flex items-center gap-2">
          <Tabs value={tab} onChange={setTab} tabs={[{ v: "calendar", l: t("plan.calendar") }, { v: "gantt", l: t("plan.gantt") }]} />
          <Button variant="ghost" className="py-1" onClick={() => setStart(addDays(start, -7))} aria-label="previous week"><ChevronLeft size={14} /></Button>
          <Button variant="ghost" className="py-1" onClick={() => setStart(weekStart(today))}>{t("plan.thisWeek")}</Button>
          <Button variant="ghost" className="py-1" onClick={() => setStart(addDays(start, 7))} aria-label="next week"><ChevronRight size={14} /></Button>
        </div>}>
        {!s ? <Loading /> : tab === "calendar" ? (
          <div className="grid grid-cols-7 gap-1.5">
            {days.map((d) => {
              const items = s.items.filter((i) => i.planned_date === d);
              const wd = new Date(d + "T12:00:00").getDay();
              return (
                <div key={d} className={clsx("rounded border min-h-[8.5rem] p-1.5", d === s.today ? "border-accent bg-accent-soft" : "border-line-soft bg-ink-850", (wd === 0 || wd === 6) && "opacity-70")}>
                  <div className="text-[11px] text-fg-3 mb-1 flex justify-between"><span>{fmtDate(d)}</span>{d === s.today && <span className="text-accent font-semibold">{t("plan.today")}</span>}</div>
                  <div className="space-y-1">
                    {items.map((i) => (
                      <button key={i.id} onClick={() => setSel(i)} className={clsx("w-full text-left rounded border px-1.5 py-0.5 text-[10.5px] leading-tight", STATUS_BG[i.status])}>
                        <span className="font-semibold">{label(i.activity)}</span><span className="text-fg-3"> · {i.bench}</span>{i.changes > 0 && <span className="text-warning"> ↻</span>}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="overflow-x-auto scroll-thin">
            <div className="grid min-w-[860px]" style={{ gridTemplateColumns: `11rem repeat(14, minmax(0, 1fr))` }}>
              <div />
              {days.map((d) => <div key={d} className={clsx("text-[10px] text-center pb-1 border-b border-line", d === s.today ? "text-accent font-semibold" : "text-fg-3")}>{fmtDate(d)}</div>)}
              {s.gantt.map((g) => (
                <div key={g.work_order} className="contents">
                  <div className="text-[11px] py-1 pr-2 border-b border-line-soft truncate"><span className="font-mono">{g.work_order}</span> <span className="text-fg-3">{g.bench}</span></div>
                  {days.map((d) => {
                    const its = g.items.filter((i) => i.planned_date === d);
                    const act = g.items.filter((i) => i.actual_date === d && i.actual_date !== i.planned_date);
                    return (
                      <div key={d} className={clsx("border-b border-l border-line-soft py-1 px-0.5 flex flex-wrap gap-0.5 items-center justify-center", d === s.today && "bg-accent-soft")}>
                        {its.map((i) => <button key={i.id} onClick={() => setSel(i)} title={`${label(i.activity)} · ${label(i.status)}`} className={clsx("rounded border px-1 text-[9.5px] font-semibold", STATUS_BG[i.status])}>{ACT_ABBR[i.activity]}</button>)}
                        {act.map((i) => <span key={`a${i.id}`} title={`${label(i.activity)} actual`} className="rounded border border-dashed border-good px-1 text-[9.5px] text-good">{ACT_ABBR[i.activity]}</span>)}
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
            <div className="flex flex-wrap gap-3 mt-2 text-[10.5px] text-fg-3">{Object.entries(ACT_ABBR).map(([k, v]) => <span key={k}><strong className="text-fg-2">{v}</strong> {label(k)}</span>)}<span className="text-good">┆ {t("plan.actualMarker")}</span></div>
          </div>
        )}
        <div className="flex flex-wrap gap-3 mt-2 text-[11px] text-fg-2">{Object.keys(STATUS_BG).map((k) => <span key={k} className="flex items-center gap-1"><span className={clsx("w-3 h-3 rounded border", STATUS_BG[k])} />{label(k)}</span>)}<span className="text-warning">↻ {t("plan.changed")}</span></div>
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Card title={t("plan.production")} subtitle={t("plan.productionSub")}>
          <div className="h-60">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={(prod.data ?? []).map((p) => ({ ...p, label: fmtDate(p.week) }))} margin={{ top: 8, right: 8, left: 4, bottom: 0 }} barGap={2}>
                <CartesianGrid stroke={chart.grid} vertical={false} />
                <XAxis dataKey="label" {...axisProps} interval={1} />
                <YAxis {...axisProps} tickFormatter={(v) => `${fmtNum(v / 1000, 0)}k`} width={40} />
                <Tooltip formatter={(v) => `${fmtNum(v as number, 0)} t`} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="forecast_t" name={t("plan.forecast")} fill={chart.series[0]} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                <Bar dataKey="actual_t" name={t("plan.actual")} fill={chart.series[1]} radius={[3, 3, 0, 0]} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title={t("plan.delays")} subtitle={t("plan.delaysSub")}>
          <div className="h-60">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={(delays.data?.pareto ?? []).map((p) => ({ ...p, label: label(p.category) }))} layout="vertical" margin={{ top: 4, right: 24, left: 8, bottom: 0 }}>
                <CartesianGrid stroke={chart.grid} horizontal={false} />
                <XAxis type="number" {...axisProps} unit=" h" />
                <YAxis type="category" dataKey="label" {...axisProps} width={130} />
                <Tooltip formatter={(v, _n, p) => [`${fmtNum(v as number)} h · ${(p.payload as { events: number }).events} ${t("dashboard.events")}`, t("plan.hours")]} />
                <Bar dataKey="hours" fill={chart.series[0]} radius={[0, 3, 3, 0]} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Card title={t("plan.workOrders")} bodyClass="p-0">
          <DataTable rows={wos.data ?? []} rowKey={(r) => r.id} pageSize={10} onRowClick={(r) => setWoSel(r)} empty={t("ops.noWorkOrders")} columns={[
            { key: "code", header: "WO", render: (r) => <span className="font-mono">{r.code}</span> },
            { key: "planned_start", header: t("plan.start") },
            { key: "engineering_forecast_ref", header: t("plan.forecastRef"), render: (r) => <span className="font-mono text-[11px]">{r.engineering_forecast_ref}</span> },
            { key: "forecast_tonnes", header: t("plan.forecastT"), align: "right", render: (r) => fmtNum(r.forecast_tonnes, 0) },
            { key: "actual_tonnes", header: t("plan.actualT"), align: "right", render: (r) => fmtNum(r.actual_tonnes, 0) },
            { key: "tonnes_variance_pct", header: "Δ %", align: "right", render: (r) => r.tonnes_variance_pct === null ? "—" : <span className={Math.abs(r.tonnes_variance_pct) > 5 ? "text-warning" : ""}>{r.tonnes_variance_pct > 0 ? "+" : ""}{fmtNum(r.tonnes_variance_pct)}</span> },
            { key: "progress_pct", header: t("plan.progress"), align: "right", render: (r) => `${r.progress_pct}%` },
            { key: "status", header: t("lab.status"), render: (r) => <StatusPill status={r.status === "OPEN" ? "PLANNED" : r.status} text={label(r.status)} /> },
          ]} />
        </Card>
        <Card title={t("plan.deliveries")} bodyClass="p-0">
          <DataTable rows={dl.data ?? []} rowKey={(r) => r.id} pageSize={10} columns={[
            { key: "code", header: "ID", render: (r) => <span className="font-mono">{r.code}</span> },
            { key: "planned_date", header: t("plan.planned") },
            { key: "product", header: t("dashboard.cols.product"), className: "max-w-[12rem] truncate" },
            { key: "area", header: t("scan.area") },
            { key: "planned_qty", header: t("plan.qty"), align: "right", render: (r) => `${r.delivered_qty !== null ? `${fmtNum(r.delivered_qty)} / ` : ""}${fmtNum(r.planned_qty)} t` },
            { key: "status", header: t("lab.status"), render: (r) => r.status === "SCHEDULED" ? <Button perm="planning.write" variant="ghost" className="text-xs py-0.5" onClick={() => setRecv(r)}><PackageCheck size={12} />{t("plan.receive")}</Button> : <StatusPill status={r.status} /> },
          ]} />
        </Card>
      </div>

      <Card title={t("plan.changes")} bodyClass="p-0">
        <DataTable rows={delays.data?.changes ?? []} rowKey={(r) => r.id} pageSize={8} columns={[
          { key: "at", header: t("lab.date"), render: (r) => r.at.slice(0, 16).replace("T", " ") },
          { key: "work_order", header: "WO", render: (r) => <span className="font-mono">{r.work_order}</span> },
          { key: "activity", header: t("plan.activity"), render: (r) => label(r.activity) },
          { key: "old_date", header: t("plan.from"), render: (r) => `${r.old_date} → ${r.new_date}` },
          { key: "cause_category", header: t("plan.cause"), render: (r) => <Pill tone="neutral">{label(r.cause_category)}</Pill> },
          { key: "cause", header: t("plan.causeDetail"), className: "max-w-md" },
          { key: "by", header: t("bo.by") },
        ]} />
      </Card>
      {sel && <ItemModal it={sel} onClose={() => setSel(null)} />}
      {recv && <ReceiveModal d={recv} onClose={() => setRecv(null)} />}
    </div>
  );
}
