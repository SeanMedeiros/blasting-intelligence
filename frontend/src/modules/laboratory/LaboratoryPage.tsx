import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { axisProps, chart } from "../../components/charts/theme";
import { Card, ErrorState, Loading, PageHeader, Pill, StatusPill } from "../../components/ui";
import { Button, Field, FormError, Input, Modal, Select, Textarea } from "../../components/ui/forms";
import { DataTable, Stat, Tabs } from "../../components/ui/table";
import { api, send } from "../../lib/api";
import { fmtDate, fmtNum, label } from "../../lib/format";
import { AttachmentsPanel } from "../../components/Attachments";

type TT = "VISCOSITY" | "DENSITY" | "VOD" | "FLOWABILITY" | "NOX";
const TYPES: TT[] = ["VISCOSITY", "DENSITY", "VOD", "FLOWABILITY", "NOX"];
const PRODUCTS: Record<TT, string[]> = { VISCOSITY: ["E-100", "P-300"], DENSITY: ["E-100", "G-200", "P-300"], VOD: ["G-200"], FLOWABILITY: ["E-100"], NOX: ["G-200"] };
const UNIT: Record<TT, string> = { VISCOSITY: "mPa·s", DENSITY: "g/cm³", VOD: "m/s", FLOWABILITY: "s", NOX: "ppm" };
const ITYPE: Record<TT, string> = { VISCOSITY: "VISCOMETER", DENSITY: "DENSITY", VOD: "VOD", FLOWABILITY: "FLOWABILITY", NOX: "NOX" };
const RESULT_COLOR: Record<string, string> = { PASS: chart.series[0], FAIL: chart.critical, NOT_EVALUATED: "#8794a8" };

interface Test {
  id: number; code: string; test_type: TT; tested_at: string; batch: string | null; product: string | null; blast: string | null; instrument: string;
  calibration_valid: boolean; technician: string; value: number | null; unit: string; limit_min: number | null; limit_max: number | null;
  result: string; data_quality: string; test_conditions: string | null; approved_test_ref: string | null; notes: string | null;
}
interface Summary {
  tests: number; by_type: Record<string, Record<string, number>>; calibration_invalid_tests: number;
  instruments: { id: number; code: string; name: string; type: string; serial: string; location: string; status: string; valid_until: string | null; last_calibrated?: string; certificate?: string }[];
  nonconformances: { id: number; code: string; raised_on: string; description: string; disposition: string | null; status: string; test: string | null; batch: string | null }[];
  batches_on_hold: { code: string; product: string; status: string; produced_on: string }[];
}
interface Trend { unit: string; limit: { min: number | null; max: number | null; source: string; is_demo_placeholder: boolean } | null; points: { code: string; date: string; value: number; result: string; batch: string }[] }

const CAL_TONE: Record<string, "good" | "warning" | "critical" | "neutral"> = { VALID: "good", DUE_SOON: "warning", EXPIRED: "critical", NO_RECORD: "neutral" };

function BatchModal({ code, onClose }: { code: string; onClose: () => void }) {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ["lab", "batch", code], queryFn: () => api<{ code: string; product_name: string; produced_on: string; quantity: number; unit: string; status: string; tests: Test[]; nonconformances: { code: string; description: string; status: string; disposition: string | null }[] }>(`/lab/batches/${code}`) });
  const b = q.data;
  return (
    <Modal title={`${t("lab.batchTrace")} — ${code}`} onClose={onClose} wide>
      {!b ? <Loading /> : (
        <div className="space-y-3">
          <div className="text-fg-2">{b.product_name} · {b.produced_on} · {fmtNum(b.quantity)} {b.unit} · <StatusPill status={b.status} text={label(b.status)} /></div>
          <table className="w-full text-[12.5px] tnum">
            <thead className="text-[11px] text-fg-3 uppercase"><tr><th className="text-left py-1">{t("lab.test")}</th><th className="text-left">{t("lab.type")}</th><th className="text-right">{t("lab.value")}</th><th className="text-left pl-3">{t("lab.instrument")}</th><th className="text-left">{t("lab.result")}</th></tr></thead>
            <tbody>{b.tests.map((x) => (
              <tr key={x.id} className="border-t border-line-soft"><td className="py-1 font-mono">{x.code}</td><td>{label(x.test_type)}</td><td className="text-right">{fmtNum(x.value, 3)} {x.unit}</td>
                <td className="pl-3">{x.instrument}{!x.calibration_valid && <span className="text-critical"> ⚠</span>}</td><td><StatusPill status={x.result} /></td></tr>
            ))}</tbody>
          </table>
          {b.nonconformances.map((n) => <div key={n.code} className="text-[12.5px] border-l-2 border-critical pl-2"><span className="font-mono">{n.code}</span> · {label(n.status)} · {n.description}</div>)}
        </div>
      )}
    </Modal>
  );
}

function RecordModal({ type, onClose }: { type: TT; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const instr = useQuery({ queryKey: ["instruments"], queryFn: () => api<{ items: { id: number; code: string; name: string; instrument_type: string }[] }>("/records/instrument", { limit: 200 }) });
  const people = useQuery({ queryKey: ["personnel"], queryFn: () => api<{ items: { id: number; full_name: string; role: string }[] }>("/records/personnel", { limit: 200 }) });
  const fieldTest = type === "VOD" || type === "NOX";
  const [f, setF] = useState({ ref: "", instrument_id: "", technician_id: "7", value: "", test_conditions: "", sample_temperature_c: "", approved_test_ref: "", data_quality: "VALID", notes: "" });
  const [res, setRes] = useState<{ result: string; reasons: string[]; code: string } | null>(null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const mut = useMutation({
    mutationFn: () => send<{ result: string; reasons: string[]; code: string }>("POST", "/lab/tests", {
      test_type: type, [fieldTest ? "blast_code" : "batch_code"]: f.ref.trim(), instrument_id: Number(f.instrument_id), technician_id: Number(f.technician_id),
      value: Number(f.value), test_conditions: f.test_conditions || null, sample_temperature_c: f.sample_temperature_c === "" ? null : Number(f.sample_temperature_c),
      approved_test_ref: f.approved_test_ref || null, data_quality: f.data_quality, notes: f.notes || null,
    }),
    onSuccess: (r) => { setRes(r); qc.invalidateQueries({ queryKey: ["lab"] }); },
  });
  return (
    <Modal title={`${t("lab.record")} — ${label(type)}`} onClose={onClose}
      footer={res ? <Button onClick={onClose}>{t("common.close")}</Button> : <><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button perm="lab.test" onClick={() => mut.mutate()} disabled={!f.ref || !f.instrument_id || f.value === "" || mut.isPending}>{t("common.save")}</Button></>}>
      {res ? (
        <div className="space-y-2"><div className="flex gap-2 items-center"><span className="font-mono">{res.code}</span><StatusPill status={res.result} /></div>
          <ul className="list-disc pl-5 text-fg-2">{res.reasons.map((r) => <li key={r}>{r}</li>)}</ul></div>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label={fieldTest ? t("lab.blastCode") : t("lab.batchCode")} hint={fieldTest ? "e.g. BL-26-0430" : "e.g. E100-261203"}>
              <Input value={f.ref} onChange={set("ref")} />
            </Field>
            <Field label={`${t("lab.value")} (${UNIT[type]})`}><Input type="number" step="any" min="0" value={f.value} onChange={set("value")} /></Field>
            <Field label={t("lab.instrument")}>
              <Select value={f.instrument_id} onChange={set("instrument_id")}>
                <option value="">—</option>
                {instr.data?.items.filter((i) => i.instrument_type === ITYPE[type]).map((i) => <option key={i.id} value={i.id}>{i.code} — {i.name}</option>)}
              </Select>
            </Field>
            <Field label={t("lab.technician")}>
              <Select value={f.technician_id} onChange={set("technician_id")}>{people.data?.items.map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}</Select>
            </Field>
            <Field label={t("lab.temperature")}><Input type="number" step="0.1" value={f.sample_temperature_c} onChange={set("sample_temperature_c")} /></Field>
            <Field label={t("lab.quality")}>
              <Select value={f.data_quality} onChange={set("data_quality")}>{["VALID", "QUESTIONABLE", "INVALID"].map((q) => <option key={q} value={q}>{label(q)}</option>)}</Select>
            </Field>
          </div>
          {fieldTest && <Field label={t("lab.approvedRef")}><Input value={f.approved_test_ref} onChange={set("approved_test_ref")} placeholder={type === "VOD" ? "TST-VOD-26" : "TST-NOX-26"} /></Field>}
          <Field label={t("lab.conditions")}><Input value={f.test_conditions} onChange={set("test_conditions")} /></Field>
          <Field label={t("dh.notes")}><Textarea value={f.notes} onChange={set("notes")} /></Field>
          <p className="text-[11px] text-fg-3">{t("lab.rule")}</p>
          <FormError error={mut.error} />
        </div>
      )}
    </Modal>
  );
}

function NcModal({ nc, onClose }: { nc: Summary["nonconformances"][number]; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [f, setF] = useState({ disposition: nc.disposition ?? "RETEST", close: false, closure_note: "", decided_by: "" });
  const mut = useMutation({ mutationFn: () => send("PATCH", `/lab/nonconformances/${nc.id}`, f), onSuccess: () => { qc.invalidateQueries({ queryKey: ["lab"] }); onClose(); } });
  return (
    <Modal title={`${t("lab.disposition")} — ${nc.code}`} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button><Button perm="lab.disposition" onClick={() => mut.mutate()} disabled={mut.isPending}>{t("common.save")}</Button></>}>
      <div className="space-y-3">
        <p className="text-fg-2 text-[13px]">{nc.description}</p>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("lab.disposition")}>
            <Select value={f.disposition} onChange={(e) => setF({ ...f, disposition: e.target.value })}>{["RETEST", "QUARANTINE", "REJECT", "USE_AS_IS_ENGINEERING"].map((d) => <option key={d} value={d}>{label(d)}</option>)}</Select>
          </Field>
          <Field label={t("lab.decidedBy")}><Input value={f.decided_by} onChange={(e) => setF({ ...f, decided_by: e.target.value })} /></Field>
        </div>
        <label className="flex items-center gap-2"><input type="checkbox" checked={f.close} onChange={(e) => setF({ ...f, close: e.target.checked })} />{t("lab.closeNc")}</label>
        {f.close && <Field label={t("lab.closureNote")}><Textarea value={f.closure_note} onChange={(e) => setF({ ...f, closure_note: e.target.value })} /></Field>}
        <FormError error={mut.error} />
        <AttachmentsPanel entity="nonconformance" entityId={nc.id} />
      </div>
    </Modal>
  );
}

function TypeTab({ type, onBatch }: { type: TT; onBatch: (c: string) => void }) {
  const { t } = useTranslation();
  const [product, setProduct] = useState(PRODUCTS[type][0]);
  const [rec, setRec] = useState(false);
  const p = PRODUCTS[type].includes(product) ? product : PRODUCTS[type][0];
  const trend = useQuery({ queryKey: ["lab", "trend", type, p], queryFn: () => api<Trend>("/lab/trend", { test_type: type, product: p }) });
  const tests = useQuery({ queryKey: ["lab", "tests", type, p], queryFn: () => api<Test[]>("/lab/tests", { test_type: type, product: p }) });
  const pts = (trend.data?.points ?? []).map((x) => ({ ...x, ts: new Date(x.date + "T12:00:00").getTime() }));
  const lim = trend.data?.limit;
  const vals = pts.map((x) => x.value).concat([lim?.min ?? NaN, lim?.max ?? NaN].filter(Number.isFinite));
  const pad = vals.length ? (Math.max(...vals) - Math.min(...vals)) * 0.12 || 1 : 1;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={p} onChange={(e) => setProduct(e.target.value)} className="max-w-[10rem] text-sm py-1" aria-label={t("lab.product")}>
          {PRODUCTS[type].map((x) => <option key={x} value={x}>{x}</option>)}
        </Select>
        <span className="text-xs text-fg-3">{t(`lab.about.${type}`)}</span>
        <Button perm="lab.test" className="ml-auto" onClick={() => setRec(true)}><Plus size={14} />{t("lab.record")}</Button>
      </div>
      <Card title={t("lab.trendTitle", { type: label(type), product: p })}
        subtitle={lim ? `${t("lab.spec")}: ${lim.min ?? "—"} – ${lim.max ?? "—"} ${trend.data?.unit}${lim.is_demo_placeholder ? " · DEMO PLACEHOLDER" : ""}` : t("lab.noLimit")}>
        {trend.isLoading ? <Loading /> : (
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart margin={{ top: 8, right: 20, left: 4, bottom: 0 }}>
                <CartesianGrid stroke={chart.grid} />
                <XAxis type="number" dataKey="ts" domain={["dataMin", "dataMax"]} {...axisProps} tickFormatter={(v) => fmtDate(new Date(v).toISOString().slice(0, 10))} />
                <YAxis type="number" dataKey="value" {...axisProps} width={64} domain={vals.length ? [Math.max(0, Math.min(...vals) - pad), Math.max(...vals) + pad] : ["auto", "auto"]}
                  tickFormatter={(v) => fmtNum(v, type === "DENSITY" ? 2 : 0)} />
                <ZAxis range={[44, 44]} />
                {lim?.min != null && <ReferenceLine y={lim.min} stroke={chart.reference} strokeDasharray="5 4" label={{ value: `min ${lim.min}`, fill: chart.tick, fontSize: 10, position: "insideBottomRight" }} />}
                {lim?.max != null && <ReferenceLine y={lim.max} stroke={chart.reference} strokeDasharray="5 4" label={{ value: `max ${lim.max}`, fill: chart.tick, fontSize: 10, position: "insideTopRight" }} />}
                <Tooltip cursor={{ stroke: chart.axis }} content={({ payload }) => {
                  const x = payload?.[0]?.payload as (typeof pts)[number] | undefined;
                  return x ? <div className="recharts-default-tooltip px-2 py-1 text-xs"><div className="font-mono">{x.code} · {x.batch}</div><div>{x.date} · {fmtNum(x.value, 3)} {trend.data?.unit} · {label(x.result)}</div></div> : null;
                }} />
                <Scatter data={pts} isAnimationActive={false}>
                  {pts.map((x) => <Cell key={x.code} fill={RESULT_COLOR[x.result]} stroke={x.result === "FAIL" ? "#fff" : "none"} />)}
                </Scatter>
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        )}
        <div className="flex gap-4 text-[11px] text-fg-2 mt-1">
          {Object.entries(RESULT_COLOR).map(([k, c]) => <span key={k} className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full" style={{ background: c }} />{label(k)}</span>)}
          <span className="flex items-center gap-1.5"><span className="w-4 border-t border-dashed border-fg-2" />{t("lab.spec")}</span>
        </div>
      </Card>
      <Card title={t("lab.records")} bodyClass="p-0">
        {tests.error && <ErrorState error={tests.error} />}
        <DataTable rows={tests.data ?? []} rowKey={(r) => r.id} columns={[
          { key: "code", header: t("lab.test"), render: (r) => <span className="font-mono">{r.code}</span> },
          { key: "tested_at", header: t("lab.date"), render: (r) => r.tested_at.slice(0, 16).replace("T", " ") },
          { key: "batch", header: t("lab.batchOrBlast"), render: (r) => r.batch ? <button className="font-mono text-accent hover:underline" onClick={() => onBatch(r.batch!)}>{r.batch}</button> : <span className="font-mono">{r.blast}</span> },
          { key: "value", header: `${t("lab.value")} (${UNIT[type]})`, align: "right", render: (r) => fmtNum(r.value, type === "DENSITY" ? 3 : 1) },
          { key: "instrument", header: t("lab.instrument"), render: (r) => <span>{r.instrument}{!r.calibration_valid && <Pill tone="critical" className="ml-1">{t("lab.calExpired")}</Pill>}</span> },
          { key: "technician", header: t("lab.technician") },
          { key: "data_quality", header: t("lab.quality"), render: (r) => label(r.data_quality) },
          { key: "result", header: t("lab.result"), render: (r) => <StatusPill status={r.result} /> },
        ]} />
      </Card>
      {rec && <RecordModal type={type} onClose={() => setRec(false)} />}
    </div>
  );
}

export default function LaboratoryPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<"overview" | TT>("overview");
  const [batch, setBatch] = useState<string | null>(null);
  const [nc, setNc] = useState<Summary["nonconformances"][number] | null>(null);
  const s = useQuery({ queryKey: ["lab", "summary"], queryFn: () => api<Summary>("/lab/summary") });
  const d = s.data;
  const fails = d ? Object.values(d.by_type).reduce((a, v) => a + (v.FAIL ?? 0), 0) : 0;
  const openNc = d?.nonconformances.filter((n) => n.status === "OPEN").length ?? 0;
  return (
    <div>
      <PageHeader title={t("lab.title")} subtitle={t("lab.subtitle")} />
      <Tabs value={tab} onChange={setTab} tabs={[{ v: "overview", l: t("lab.overview"), badge: openNc }, ...TYPES.map((x) => ({ v: x, l: label(x) }))]} />
      {tab === "overview" && (
        s.isLoading ? <Loading /> : d && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
              <Stat label={t("lab.tests30")} value={d.tests} />
              <Stat label={t("lab.fails30")} value={fails} tone={fails ? "critical" : undefined} />
              <Stat label={t("lab.calInvalid")} value={d.calibration_invalid_tests} tone={d.calibration_invalid_tests ? "warning" : undefined} sub={t("lab.notEvaluated")} />
              <Stat label={t("lab.openNc")} value={openNc} tone={openNc ? "warning" : "good"} />
              <Stat label={t("lab.onHold")} value={d.batches_on_hold.length} sub={d.batches_on_hold.map((b) => b.code).join(", ")} />
            </div>
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
              <Card title={t("lab.byType")} bodyClass="p-0">
                <table className="w-full text-[12.5px] tnum">
                  <thead className="text-[11px] uppercase text-fg-3"><tr className="border-b border-line-soft"><th className="text-left px-3 py-2">{t("lab.type")}</th>{["PASS", "FAIL", "NOT_EVALUATED"].map((r) => <th key={r} className="text-right px-3">{label(r)}</th>)}</tr></thead>
                  <tbody>{TYPES.map((x) => (
                    <tr key={x} className="border-b border-line-soft last:border-0 hover:bg-ink-750 cursor-pointer" onClick={() => setTab(x)}>
                      <td className="px-3 py-1.5 flex items-center gap-2"><FlaskConical size={13} className="text-fg-3" />{label(x)}</td>
                      {["PASS", "FAIL", "NOT_EVALUATED"].map((r) => <td key={r} className={`text-right px-3 ${r === "FAIL" && d.by_type[x]?.[r] ? "text-critical font-semibold" : ""}`}>{d.by_type[x]?.[r] ?? 0}</td>)}
                    </tr>
                  ))}</tbody>
                </table>
              </Card>
              <Card title={t("lab.calibration")} bodyClass="p-0">
                <DataTable rows={d.instruments} rowKey={(r) => r.id} maxHeight="16rem" columns={[
                  { key: "code", header: t("lab.instrument"), render: (r) => <span><span className="font-mono">{r.code}</span> <span className="text-fg-3">{r.name}</span></span> },
                  { key: "certificate", header: t("lab.certificate"), render: (r) => <span className="font-mono text-[11.5px]">{r.certificate ?? "—"}</span> },
                  { key: "valid_until", header: t("lab.validUntil") },
                  { key: "status", header: t("lab.status"), render: (r) => <Pill tone={CAL_TONE[r.status]}>{t(`lab.cal.${r.status}`)}</Pill> },
                ]} />
              </Card>
            </div>
            <Card title={t("lab.ncTitle")} bodyClass="p-0">
              <DataTable rows={d.nonconformances} rowKey={(r) => r.id} onRowClick={(r) => r.status === "OPEN" && setNc(r)} columns={[
                { key: "code", header: "NC", render: (r) => <span className="font-mono">{r.code}</span> },
                { key: "raised_on", header: t("lab.date") },
                { key: "batch", header: t("lab.batchCode"), render: (r) => r.batch ? <button className="font-mono text-accent hover:underline" onClick={(e) => { e.stopPropagation(); setBatch(r.batch!); }}>{r.batch}</button> : "—" },
                { key: "description", header: t("lab.description"), className: "max-w-xl", render: (r) => <span className="text-fg-2">{r.description}</span> },
                { key: "disposition", header: t("lab.disposition"), render: (r) => label(r.disposition) },
                { key: "status", header: t("lab.status"), render: (r) => <StatusPill status={r.status === "OPEN" ? "OPEN" : "CLOSED"} text={label(r.status)} /> },
              ]} />
              <p className="px-3 py-2 text-[11px] text-fg-3">{t("lab.ncHint")}</p>
            </Card>
          </div>
        )
      )}
      {tab !== "overview" && <TypeTab key={tab} type={tab} onBatch={setBatch} />}
      {batch && <BatchModal code={batch} onClose={() => setBatch(null)} />}
      {nc && <NcModal nc={nc} onClose={() => setNc(null)} />}
    </div>
  );
}
