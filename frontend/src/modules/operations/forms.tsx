/** Creation forms for operational records (work orders, schedule, deliveries, patterns, blasts, detonator issue). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, Upload } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Pill } from "../../components/ui";
import { Button, Field, FormError, Input, Modal, Select, Textarea } from "../../components/ui/forms";
import { api, send, upload, withLang } from "../../lib/api";
import { addDays, useToday } from "../../lib/dates";
import { label } from "../../lib/format";
import { useOptions } from "../../lib/options";
import { AttachmentsPanel } from "../../components/Attachments";

interface OpsOptions {
  work_orders: { id: number; label: string; area_id: number; type: string }[];
  patterns_free: { id: number; label: string; area_id: number; has_holes: boolean }[];
  blasts_without_detonator_record: { id: number; label: string }[];
  activities: string[];
  wo_types: string[];
}

export function useOpsOptions() {
  return useQuery({ queryKey: ["ops", "options"], queryFn: () => api<OpsOptions>("/ops/options") });
}

function useInvalidate() {
  const qc = useQueryClient();
  return () => ["ops", "plan", "dh", "blasts", "det", "md", "dashboard"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
}

type Setter<T> = (k: keyof T) => (e: { target: { value: string } }) => void;
function useForm<T extends Record<string, string>>(init: T): [T, Setter<T>, (v: T) => void] {
  const [f, setF] = useState(init);
  return [f, (k) => (e) => setF({ ...f, [k]: e.target.value }), setF];
}
const num = (v: string) => (v === "" ? null : Number(v));
const idOrNull = (v: string) => (v ? Number(v) : null);

function OptionSelect({ entity, value, onChange, required }: { entity: string; value: string; onChange: (e: { target: { value: string } }) => void; required?: boolean }) {
  const { t } = useTranslation();
  const o = useOptions(entity);
  return <Select value={value} onChange={onChange}><option value="">{required ? t("common.choose") : "—"}</option>{o.data?.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</Select>;
}

// ----------------------------------------------------------------------------- work orders
export function NewWorkOrderModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const today = useToday();
  const inv = useInvalidate();
  const [f, set] = useForm({ code: "", title: "", area_id: "", wo_type: "BLAST", engineering_forecast_ref: "", planned_start: today, planned_end: addDays(today, 10), forecast_tonnes: "" });
  const mut = useMutation({
    mutationFn: () => send("POST", "/ops/work-orders", { ...f, code: f.code || null, area_id: Number(f.area_id), forecast_tonnes: num(f.forecast_tonnes), engineering_forecast_ref: f.engineering_forecast_ref || null }),
    onSuccess: () => { inv(); onClose(); },
  });
  return (
    <Modal title={t("ops.newWorkOrder")} onClose={onClose} footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
      <Button perm="planning.write" onClick={() => mut.mutate()} disabled={f.title.length < 3 || !f.area_id || mut.isPending}>{t("common.save")}</Button></>}>
      <div className="grid grid-cols-2 gap-3">
        <Field label={t("ops.title")} className="col-span-2"><Input value={f.title} onChange={set("title")} /></Field>
        <Field label={t("scan.area")}><OptionSelect entity="area" value={f.area_id} onChange={set("area_id")} required /></Field>
        <Field label={t("ops.type")}><Select value={f.wo_type} onChange={set("wo_type")}>{["BLAST", "SURVEY_CAMPAIGN", "LAB_SAMPLING"].map((x) => <option key={x} value={x}>{label(x)}</option>)}</Select></Field>
        <Field label={t("ops.plannedStart")}><Input type="date" value={f.planned_start} onChange={set("planned_start")} /></Field>
        <Field label={t("ops.plannedEnd")}><Input type="date" value={f.planned_end} onChange={set("planned_end")} /></Field>
        <Field label={t("ops.forecastRef")}><Input value={f.engineering_forecast_ref} onChange={set("engineering_forecast_ref")} /></Field>
        <Field label={t("ops.forecastT")}><Input type="number" min="0" value={f.forecast_tonnes} onChange={set("forecast_tonnes")} /></Field>
        <Field label={t("ops.code")} hint={t("ops.codeHint")} className="col-span-2"><Input value={f.code} onChange={set("code")} placeholder="WO-YY-NNNN" /></Field>
      </div>
      <div className="mt-3"><FormError error={mut.error} /></div>
    </Modal>
  );
}

export function WorkOrderModal({ wo, onClose }: { wo: { id: number; code: string; title: string; status: string }; onClose: () => void }) {
  const { t } = useTranslation();
  const today = useToday();
  const inv = useInvalidate();
  const opts = useOpsOptions();
  const [std, setStd] = useState({ blast_date: addDays(today, 5), responsible_id: "" });
  const [act, setAct] = useState({ activity: "DRILLING", planned_date: today, resources: "", responsible_id: "" });
  const [reason, setReason] = useState("");
  const [tonnes, setTonnes] = useState("");
  const done = () => { inv(); };
  const stdMut = useMutation({ mutationFn: () => send<{ created: string[] }>("POST", `/ops/work-orders/${wo.id}/standard-schedule`, { blast_date: std.blast_date, responsible_id: idOrNull(std.responsible_id) }), onSuccess: done });
  const actMut = useMutation({ mutationFn: () => send("POST", `/ops/work-orders/${wo.id}/schedule-items`, { ...act, resources: act.resources || null, responsible_id: idOrNull(act.responsible_id) }), onSuccess: done });
  const stMut = useMutation({
    mutationFn: (status: string) => send("PATCH", `/ops/work-orders/${wo.id}`, { status, reason: reason || null, ...(status === "COMPLETED" && tonnes ? { actual_tonnes: Number(tonnes) } : {}) }),
    onSuccess: () => { inv(); onClose(); },
  });
  const closed = ["COMPLETED", "CANCELLED"].includes(wo.status);
  return (
    <Modal wide title={`${wo.code} — ${wo.title}`} onClose={onClose}>
      <div className="flex items-center gap-2 mb-4"><Pill tone={closed ? "neutral" : "info"}>{label(wo.status)}</Pill></div>
      <div className="mb-5"><AttachmentsPanel entity="work_order" entityId={wo.id} /></div>
      {!closed && (
        <div className="space-y-5">
          <section>
            <h4 className="text-xs uppercase text-fg-3 mb-2">{t("ops.standardSchedule")}</h4>
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t("ops.blastDate")}><Input type="date" value={std.blast_date} onChange={(e) => setStd({ ...std, blast_date: e.target.value })} /></Field>
              <Field label={t("qsse.responsible")}><OptionSelect entity="personnel" value={std.responsible_id} onChange={(e) => setStd({ ...std, responsible_id: e.target.value })} /></Field>
              <Button perm="planning.write" onClick={() => stdMut.mutate()} disabled={stdMut.isPending}>{t("ops.createSequence")}</Button>
            </div>
            <p className="text-[11px] text-fg-3 mt-1">{stdMut.data ? t("ops.sequenceCreated", { n: stdMut.data.created.length }) : t("ops.sequenceHint")}</p>
            <FormError error={stdMut.error} />
          </section>
          <section>
            <h4 className="text-xs uppercase text-fg-3 mb-2">{t("ops.addActivity")}</h4>
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t("ops.activity")}><Select value={act.activity} onChange={(e) => setAct({ ...act, activity: e.target.value })}>{(opts.data?.activities ?? []).map((a) => <option key={a} value={a}>{label(a)}</option>)}</Select></Field>
              <Field label={t("ops.date")}><Input type="date" value={act.planned_date} onChange={(e) => setAct({ ...act, planned_date: e.target.value })} /></Field>
              <Field label={t("ops.resources")}><Input value={act.resources} onChange={(e) => setAct({ ...act, resources: e.target.value })} className="w-40" /></Field>
              <Field label={t("qsse.responsible")}><OptionSelect entity="personnel" value={act.responsible_id} onChange={(e) => setAct({ ...act, responsible_id: e.target.value })} /></Field>
              <Button perm="planning.write" variant="ghost" onClick={() => actMut.mutate()} disabled={actMut.isPending}>{t("ops.add")}</Button>
            </div>
            {actMut.isSuccess && <p className="text-[11px] text-good mt-1">{t("ops.added")}</p>}
            <FormError error={actMut.error} />
          </section>
          <section className="border-t border-line-soft pt-4">
            <h4 className="text-xs uppercase text-fg-3 mb-2">{t("ops.status")}</h4>
            <div className="flex flex-wrap items-end gap-2">
              {wo.status === "OPEN" && <Button perm="planning.write" variant="ghost" onClick={() => stMut.mutate("IN_PROGRESS")}>{t("ops.start")}</Button>}
              {wo.status === "IN_PROGRESS" && <>
                <Field label={t("ops.actualT")}><Input type="number" min="0" value={tonnes} onChange={(e) => setTonnes(e.target.value)} className="w-32" /></Field>
                <Button perm="planning.write" variant="ghost" onClick={() => stMut.mutate("COMPLETED")}>{t("ops.complete")}</Button>
              </>}
              <Field label={t("ops.cancelReason")}><Input value={reason} onChange={(e) => setReason(e.target.value)} className="w-64" /></Field>
              <Button perm="planning.write" variant="danger" onClick={() => stMut.mutate("CANCELLED")} disabled={reason.length < 3}>{t("ops.cancelWo")}</Button>
            </div>
            <FormError error={stMut.error} />
          </section>
        </div>
      )}
    </Modal>
  );
}

export function NewDeliveryModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const today = useToday();
  const inv = useInvalidate();
  const [f, set] = useForm({ product_name: "", destination_area_id: "", planned_date: addDays(today, 1), planned_qty: "", unit: "t", document_ref: "" });
  const mut = useMutation({
    mutationFn: () => send("POST", "/ops/deliveries", { ...f, destination_area_id: Number(f.destination_area_id), planned_qty: Number(f.planned_qty), document_ref: f.document_ref || null }),
    onSuccess: () => { inv(); onClose(); },
  });
  return (
    <Modal title={t("ops.newDelivery")} onClose={onClose} footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
      <Button perm="planning.write" onClick={() => mut.mutate()} disabled={f.product_name.length < 2 || !f.destination_area_id || !f.planned_qty || mut.isPending}>{t("common.save")}</Button></>}>
      <div className="grid grid-cols-2 gap-3">
        <Field label={t("bo.product")} className="col-span-2"><Input value={f.product_name} onChange={set("product_name")} /></Field>
        <Field label={t("scan.area")}><OptionSelect entity="area" value={f.destination_area_id} onChange={set("destination_area_id")} required /></Field>
        <Field label={t("ops.date")}><Input type="date" value={f.planned_date} onChange={set("planned_date")} /></Field>
        <Field label={t("bo.qty")}><Input type="number" min="0" step="0.001" value={f.planned_qty} onChange={set("planned_qty")} /></Field>
        <Field label={t("md.field.unit")}><Select value={f.unit} onChange={set("unit")}>{["t", "kg", "units"].map((u) => <option key={u}>{u}</option>)}</Select></Field>
        <Field label={t("bo.doc")} className="col-span-2"><Input value={f.document_ref} onChange={set("document_ref")} /></Field>
      </div>
      <div className="mt-3"><FormError error={mut.error} /></div>
    </Modal>
  );
}

// ----------------------------------------------------------------------------- patterns
export function NewPatternModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: number) => void }) {
  const { t } = useTranslation();
  const inv = useInvalidate();
  const [f, set] = useForm({ code: "", bench_id: "", design_document_ref: "", approved_by: "", hole_diameter_mm: "" });
  const mut = useMutation({
    mutationFn: () => send<{ id: number }>("POST", "/ops/patterns", { ...f, code: f.code || null, bench_id: Number(f.bench_id), hole_diameter_mm: Number(f.hole_diameter_mm) }),
    onSuccess: (r) => { inv(); onCreated(r.id); },
  });
  return (
    <Modal title={t("ops.newPattern")} onClose={onClose} footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
      <Button perm="pattern.manage" onClick={() => mut.mutate()} disabled={!f.bench_id || f.design_document_ref.length < 2 || f.approved_by.length < 3 || !f.hole_diameter_mm || mut.isPending}>{t("ops.createThenImport")}</Button></>}>
      <div className="grid grid-cols-2 gap-3">
        <Field label={t("md.field.bench_id", { defaultValue: "Bench" })}><OptionSelect entity="bench" value={f.bench_id} onChange={set("bench_id")} required /></Field>
        <Field label={t("ops.diameter")}><Input type="number" min="20" max="500" value={f.hole_diameter_mm} onChange={set("hole_diameter_mm")} /></Field>
        <Field label={t("ops.designDoc")} hint={t("ops.designDocHint")} className="col-span-2"><Input value={f.design_document_ref} onChange={set("design_document_ref")} /></Field>
        <Field label={t("ops.approvedBy")} className="col-span-2"><Input value={f.approved_by} onChange={set("approved_by")} /></Field>
        <Field label={t("ops.code")} hint={t("ops.codeHint")} className="col-span-2"><Input value={f.code} onChange={set("code")} /></Field>
      </div>
      <div className="mt-3"><FormError error={mut.error} /></div>
    </Modal>
  );
}

interface ImportSummary { holes: number; rows: number; errors: string[]; error_count: number; replaces: number; dry_run: boolean; extent: { x: number[]; y: number[] } | null; depth_m: number[] | null }

export function HoleImportModal({ pattern, onClose }: { pattern: { id: number; code: string }; onClose: () => void }) {
  const { t } = useTranslation();
  const inv = useInvalidate();
  const [file, setFile] = useState<File | null>(null);
  const [res, setRes] = useState<ImportSummary | null>(null);
  const run = useMutation({
    mutationFn: (dry: boolean) => { const fd = new FormData(); fd.append("file", file!); return upload<ImportSummary>(`/ops/patterns/${pattern.id}/holes/import?dry_run=${dry}`, fd); },
    onSuccess: (r) => { setRes(r); if (!r.dry_run) inv(); },
  });
  const imported = res && !res.dry_run;
  return (
    <Modal wide title={`${t("ops.importDesign")} — ${pattern.code}`} onClose={onClose}
      footer={imported ? <Button onClick={onClose}>{t("common.close")}</Button> : <>
        <a href={withLang("/api/v1/ops/patterns/holes-template.csv")} download className="mr-auto"><Button variant="ghost"><Download size={14} />{t("ops.template")}</Button></a>
        <Button variant="ghost" onClick={() => run.mutate(true)} disabled={!file || run.isPending}>{t("vib.validateOnly")}</Button>
        <Button perm="pattern.manage" onClick={() => run.mutate(false)} disabled={!file || run.isPending || !res || res.error_count > 0}><Upload size={14} />{t("ops.importNow")}</Button></>}>
      <p className="text-[12.5px] text-fg-2 mb-3">{t("ops.importHelp")}</p>
      <input type="file" accept=".csv,.txt" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setRes(null); }} className="text-sm" />
      {res && (
        <div className="mt-4 space-y-2 text-sm">
          {imported ? <div className="flex items-center gap-2 text-good"><CheckCircle2 size={16} />{t("ops.imported", { n: res.holes })}</div> : (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 tnum">
              <div><div className="text-[11px] text-fg-3">{t("ops.holes")}</div><div className="font-semibold">{res.holes}</div></div>
              <div><div className="text-[11px] text-fg-3">{t("ops.rows")}</div><div className="font-semibold">{res.rows}</div></div>
              <div><div className="text-[11px] text-fg-3">{t("ops.depthRange")}</div><div className="font-semibold">{res.depth_m ? `${res.depth_m[0]}–${res.depth_m[1]} m` : "—"}</div></div>
              <div><div className="text-[11px] text-fg-3">{t("ops.replaces")}</div><div className="font-semibold">{res.replaces}</div></div>
            </div>
          )}
          {res.error_count > 0 && (
            <div className="rounded border border-critical/40 bg-critical/10 p-3 text-[12.5px]">
              <div className="font-medium mb-1">{t("ops.errors", { n: res.error_count })}</div>
              <ul className="list-disc pl-5 max-h-40 overflow-y-auto scroll-thin">{res.errors.map((e) => <li key={e}>{e}</li>)}</ul>
            </div>
          )}
          {res.dry_run && res.error_count === 0 && <p className="text-good text-[12.5px]">{t("ops.validOk")}</p>}
        </div>
      )}
      <div className="mt-3"><FormError error={run.error} /></div>
    </Modal>
  );
}

export function PatternActions({ p, onDeleted }: { p: { id: number; code: string; drilled_on: string | null; holes: unknown[]; blast: unknown | null; locked: boolean }; onDeleted: () => void }) {
  const { t } = useTranslation();
  const today = useToday();
  const inv = useInvalidate();
  const [mode, setMode] = useState<"" | "import" | "drilled" | "loading">("");
  const [drilled, setDrilled] = useState(today);
  const [ref, setRef] = useState({ document_ref: "", revision: "A", approved_by: "", approved_on: today, notes: "" });
  const drill = useMutation({ mutationFn: () => send("POST", `/ops/patterns/${p.id}/drilled`, { drilled_on: drilled }), onSuccess: () => { inv(); setMode(""); } });
  const load = useMutation({ mutationFn: () => send("POST", `/ops/patterns/${p.id}/loading-references`, { ...ref, notes: ref.notes || null }), onSuccess: () => { inv(); setMode(""); } });
  const del = useMutation({ mutationFn: () => send("DELETE", `/ops/patterns/${p.id}`), onSuccess: () => { inv(); onDeleted(); } });
  const hasMeas = (p.holes as { status: string }[]).some((h) => h.status !== "NOT_MEASURED");
  return (
    <div className="flex flex-wrap gap-2 items-center">
      {!hasMeas && <Button perm="pattern.manage" variant={p.holes.length ? "ghost" : "primary"} onClick={() => setMode("import")}><Upload size={14} />{p.holes.length ? t("ops.reimport") : t("ops.importDesign")}</Button>}
      {p.holes.length > 0 && !p.drilled_on && <Button perm="pattern.manage" variant="ghost" onClick={() => setMode("drilled")}>{t("ops.recordDrilled")}</Button>}
      <Button perm="pattern.manage" variant="ghost" onClick={() => setMode("loading")}>{t("ops.addLoadingRef")}</Button>
      {!p.blast && !hasMeas && <Button perm="pattern.manage" variant="ghost" onClick={() => { if (window.confirm(t("ops.confirmDeletePattern"))) del.mutate(); }}>{t("md.delete")}</Button>}
      <FormError error={del.error} />
      {mode === "import" && <HoleImportModal pattern={p} onClose={() => setMode("")} />}
      {mode === "drilled" && (
        <Modal title={`${t("ops.recordDrilled")} — ${p.code}`} onClose={() => setMode("")} footer={<><Button variant="ghost" onClick={() => setMode("")}>{t("common.cancel")}</Button><Button perm="pattern.manage" onClick={() => drill.mutate()}>{t("common.save")}</Button></>}>
          <Field label={t("ops.drilledOn")}><Input type="date" max={today} value={drilled} onChange={(e) => setDrilled(e.target.value)} /></Field>
          <div className="mt-3"><FormError error={drill.error} /></div>
        </Modal>
      )}
      {mode === "loading" && (
        <Modal title={`${t("ops.addLoadingRef")} — ${p.code}`} onClose={() => setMode("")} footer={<><Button variant="ghost" onClick={() => setMode("")}>{t("common.cancel")}</Button>
          <Button perm="pattern.manage" onClick={() => load.mutate()} disabled={ref.document_ref.length < 2 || ref.approved_by.length < 3}>{t("common.save")}</Button></>}>
          <p className="text-[12px] text-fg-3 mb-3">{t("ops.loadingRefNote")}</p>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("ops.documentRef")}><Input value={ref.document_ref} onChange={(e) => setRef({ ...ref, document_ref: e.target.value })} /></Field>
            <Field label={t("ops.revision")}><Input value={ref.revision} onChange={(e) => setRef({ ...ref, revision: e.target.value })} /></Field>
            <Field label={t("ops.approvedBy")}><Input value={ref.approved_by} onChange={(e) => setRef({ ...ref, approved_by: e.target.value })} /></Field>
            <Field label={t("ops.approvedOn")}><Input type="date" value={ref.approved_on} onChange={(e) => setRef({ ...ref, approved_on: e.target.value })} /></Field>
            <Field label={t("ops.notes")} className="col-span-2"><Textarea rows={2} value={ref.notes} onChange={(e) => setRef({ ...ref, notes: e.target.value })} /></Field>
          </div>
          <div className="mt-3"><FormError error={load.error} /></div>
        </Modal>
      )}
    </div>
  );
}

// ----------------------------------------------------------------------------- blasts
export function NewBlastModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: number) => void }) {
  const { t } = useTranslation();
  const today = useToday();
  const inv = useInvalidate();
  const opts = useOpsOptions();
  const [f, set] = useForm({ code: "", work_order_id: "", pattern_id: "", approved_plan_ref: "", planned_date: addDays(today, 3), supervisor_id: "", blaster_id: "", equipment_codes: "", rock_tonnes_forecast: "" });
  const wo = opts.data?.work_orders.find((w) => String(w.id) === f.work_order_id);
  const pats = (opts.data?.patterns_free ?? []).filter((p) => !wo || p.area_id === wo.area_id);
  const mut = useMutation({
    mutationFn: () => send<{ id: number }>("POST", "/ops/blasts", {
      ...f, code: f.code || null, work_order_id: Number(f.work_order_id), pattern_id: Number(f.pattern_id), supervisor_id: idOrNull(f.supervisor_id),
      blaster_id: idOrNull(f.blaster_id), equipment_codes: f.equipment_codes || null, rock_tonnes_forecast: num(f.rock_tonnes_forecast),
    }),
    onSuccess: (r) => { inv(); onCreated(r.id); },
  });
  return (
    <Modal wide title={t("ops.newBlast")} onClose={onClose} footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
      <Button perm="planning.write" onClick={() => mut.mutate()} disabled={!f.work_order_id || !f.pattern_id || f.approved_plan_ref.length < 2 || mut.isPending}>{t("common.save")}</Button></>}>
      <div className="grid sm:grid-cols-2 gap-3">
        <Field label={t("ops.workOrder")}><Select value={f.work_order_id} onChange={set("work_order_id")}><option value="">{t("common.choose")}</option>
          {opts.data?.work_orders.filter((w) => w.type === "BLAST").map((w) => <option key={w.id} value={w.id}>{w.label}</option>)}</Select></Field>
        <Field label={t("ops.pattern")} hint={t("ops.patternHint")}><Select value={f.pattern_id} onChange={set("pattern_id")}><option value="">{t("common.choose")}</option>
          {pats.map((p) => <option key={p.id} value={p.id} disabled={!p.has_holes}>{p.label}{p.has_holes ? "" : ` — ${t("ops.noDesign")}`}</option>)}</Select></Field>
        <Field label={t("ops.planRef")} hint={t("ops.planRefHint")}><Input value={f.approved_plan_ref} onChange={set("approved_plan_ref")} /></Field>
        <Field label={t("ops.plannedDate")}><Input type="date" value={f.planned_date} onChange={set("planned_date")} /></Field>
        <Field label={t("ops.supervisor")}><OptionSelect entity="personnel" value={f.supervisor_id} onChange={set("supervisor_id")} /></Field>
        <Field label={t("ops.blaster")}><OptionSelect entity="personnel" value={f.blaster_id} onChange={set("blaster_id")} /></Field>
        <Field label={t("ops.equipment")}><Input value={f.equipment_codes} onChange={set("equipment_codes")} /></Field>
        <Field label={t("ops.forecastT")}><Input type="number" min="0" value={f.rock_tonnes_forecast} onChange={set("rock_tonnes_forecast")} /></Field>
        <Field label={t("ops.code")} hint={t("ops.codeHint")}><Input value={f.code} onChange={set("code")} placeholder="BL-YY-NNNN" /></Field>
      </div>
      <p className="text-[11.5px] text-fg-3 mt-3">{t("ops.blastNote")}</p>
      <div className="mt-3"><FormError error={mut.error} /></div>
    </Modal>
  );
}

export function DeleteBlastButton({ id, onDeleted }: { id: number; onDeleted: () => void }) {
  const { t } = useTranslation();
  const inv = useInvalidate();
  const del = useMutation({ mutationFn: () => send("DELETE", `/ops/blasts/${id}`), onSuccess: () => { inv(); onDeleted(); } });
  return <span className="inline-flex flex-col gap-1"><Button perm="planning.write" variant="ghost" onClick={() => { if (window.confirm(t("ops.confirmDeleteBlast"))) del.mutate(); }}>{t("ops.deleteBlast")}</Button><FormError error={del.error} /></span>;
}

export function DetonatorIssueModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const inv = useInvalidate();
  const opts = useOpsOptions();
  const [f, set] = useForm({ blast_id: "", inventory_lot_ref: "", units_issued: "", equipment_ref: "", authorized_personnel: "", procedure_ref: "" });
  const mut = useMutation({
    mutationFn: () => send("POST", `/ops/blasts/${f.blast_id}/detonator-record`, { inventory_lot_ref: f.inventory_lot_ref, units_issued: Number(f.units_issued), equipment_ref: f.equipment_ref || null, authorized_personnel: f.authorized_personnel, procedure_ref: f.procedure_ref }),
    onSuccess: () => { inv(); onClose(); },
  });
  return (
    <Modal title={t("ops.detIssue")} onClose={onClose} footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
      <Button perm="detonator.record" onClick={() => mut.mutate()} disabled={!f.blast_id || f.inventory_lot_ref.length < 2 || !f.units_issued || f.authorized_personnel.length < 3 || f.procedure_ref.length < 2 || mut.isPending}>{t("common.save")}</Button></>}>
      <p className="text-[12px] text-fg-3 mb-3">{t("ops.detNote")}</p>
      <div className="grid grid-cols-2 gap-3">
        <Field label={t("ops.blast")}><Select value={f.blast_id} onChange={set("blast_id")}><option value="">{t("common.choose")}</option>{opts.data?.blasts_without_detonator_record.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}</Select></Field>
        <Field label={t("ops.lot")}><Input value={f.inventory_lot_ref} onChange={set("inventory_lot_ref")} /></Field>
        <Field label={t("ops.unitsIssued")}><Input type="number" min="1" value={f.units_issued} onChange={set("units_issued")} /></Field>
        <Field label={t("ops.equipmentTag")}><Input value={f.equipment_ref} onChange={set("equipment_ref")} /></Field>
        <Field label={t("ops.authorizedPersonnel")} className="col-span-2"><Input value={f.authorized_personnel} onChange={set("authorized_personnel")} /></Field>
        <Field label={t("ops.procedureRef")} className="col-span-2"><Input value={f.procedure_ref} onChange={set("procedure_ref")} /></Field>
      </div>
      <div className="mt-3"><FormError error={mut.error} /></div>
    </Modal>
  );
}

// ----------------------------------------------------------------------------- templates (Settings)
interface Templates {
  blast_checkpoints: { items: [string, string][]; is_default: boolean };
  pre_blast_checklist: { items: string[]; is_default: boolean };
  standard_schedule: { items: [string, number][]; is_default: boolean };
  lab_sampling_plan: { items: [string, string][]; is_default: boolean };
  _meta: { stages: string[]; activities: string[]; test_types: string[]; required_checkpoint: string; note: string };
}

export function TemplatesCardBody() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["ops", "templates"], queryFn: () => api<Templates>("/ops/templates") });
  const [edit, setEdit] = useState<keyof Omit<Templates, "_meta"> | null>(null);
  const [text, setText] = useState("");
  const [source, setSource] = useState("");
  const toText = (name: string, d: Templates) =>
    name === "pre_blast_checklist" ? d.pre_blast_checklist.items.join("\n")
      : name === "blast_checkpoints" ? d.blast_checkpoints.items.map(([s, n]) => `${s} | ${n}`).join("\n")
      : name === "lab_sampling_plan" ? d.lab_sampling_plan.items.map(([s, ty]) => `${s} | ${ty}`).join("\n")
      : d.standard_schedule.items.map(([a, o]) => `${a} | ${o}`).join("\n");
  const parse = (name: string): unknown[] => text.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
    if (name === "pre_blast_checklist") return l;
    const [a, b] = l.split("|").map((x) => x.trim());
    if (name === "lab_sampling_plan") return [a.toUpperCase(), (b ?? "").toUpperCase()];
    return name === "standard_schedule" ? [a, Number(b)] : [a, b ?? ""];
  });
  const mut = useMutation({
    mutationFn: () => send("PUT", `/ops/templates/${edit}`, { items: parse(edit!), source_document: source }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["ops", "templates"] }); setEdit(null); },
  });
  if (!q.data) return null;
  const d = q.data;
  return (
    <div className="space-y-3 text-sm">
      <p className="text-[12px] text-fg-3">{t("ops.templatesNote")}</p>
      {(["blast_checkpoints", "pre_blast_checklist", "standard_schedule", "lab_sampling_plan"] as const).map((name) => (
        <div key={name} className="flex items-center justify-between border-b border-line-soft pb-2 gap-3">
          <div>
            <div className="font-medium">{t(`ops.tpl.${name}`)}</div>
            <div className="text-[11px] text-fg-3">{t("ops.tplCount", { n: d[name].items.length })} · {d[name].is_default ? t("ops.tplDefault") : t("ops.tplSite")}</div>
          </div>
          <Button perm="masterdata.manage" variant="ghost" className="text-xs py-1" onClick={() => { setEdit(name); setText(toText(name, d)); setSource(""); }}>{t("common.edit")}</Button>
        </div>
      ))}
      {edit && (
        <Modal wide title={t(`ops.tpl.${edit}`)} onClose={() => setEdit(null)} footer={<><Button variant="ghost" onClick={() => setEdit(null)}>{t("common.cancel")}</Button>
          <Button perm="masterdata.manage" onClick={() => mut.mutate()} disabled={source.length < 3 || mut.isPending}>{t("common.save")}</Button></>}>
          <p className="text-[12px] text-fg-3 mb-2">{t(`ops.tplHelp.${edit}`, { stages: d._meta.stages.join(", "), activities: d._meta.activities.join(", "), types: d._meta.test_types.join(", "), required: d._meta.required_checkpoint })}</p>
          <Textarea rows={14} value={text} onChange={(e) => setText(e.target.value)} className="font-mono text-[12px]" />
          <Field label={t("ops.tplSource")} className="mt-3"><Input value={source} onChange={(e) => setSource(e.target.value)} /></Field>
          <div className="mt-3"><FormError error={mut.error} /></div>
        </Modal>
      )}
    </div>
  );
}
