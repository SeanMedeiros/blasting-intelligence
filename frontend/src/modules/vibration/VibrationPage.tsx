import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Download, TrendingUp, Upload } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { CartesianGrid, Cell, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { axisProps, chart } from "../../components/charts/theme";
import { Card, Empty, Loading, PageHeader, Pill, Progress } from "../../components/ui";
import { Button, Field, FormError, Input, Modal, Select, Textarea } from "../../components/ui/forms";
import { DataTable } from "../../components/ui/table";
import { api, send, upload, withLang } from "../../lib/api";
import { fmtDate, fmtNum, label } from "../../lib/format";

interface Station {
  code: string; name: string; type: string; instrument: string; calibration_valid_until: string | null; events: number; events_30d: number;
  valid_pct: number | null; max_ppv_30d: number | null; mean_ppv: number | null; exceedances: number; trend_slope_mm_s_per_event: number;
  limit_ppv_mm_s: number | null; limit_source: string | null; limit_is_demo: boolean;
}
interface Ev {
  id: number; code: string; station: string; station_name: string; blast: string | null; recorded_at: string; distance_m: number | null;
  ppv_mm_s: number | null; ppv_transverse: number | null; ppv_vertical: number | null; ppv_longitudinal: number | null;
  dominant_frequency_hz: number | null; air_overpressure_db: number | null; data_quality: string; quality_notes: string | null;
  limit_ppv_mm_s: number | null; compliance: string; pct_of_limit: number | null;
}
interface Wave { available: boolean; reason?: string; t: number[]; transverse: number[]; vertical: number[]; longitudinal: number[]; sample_rate_hz: number }

const COMP_COLOR: Record<string, string> = { COMPLIANT: chart.series[0], EXCEEDANCE: chart.critical, NOT_EVALUATED: "#8794a8" };
const COMP_TONE: Record<string, "good" | "critical" | "neutral"> = { COMPLIANT: "good", EXCEEDANCE: "critical", NOT_EVALUATED: "neutral" };

function Waveforms({ id, ppv }: { id: number; ppv: number }) {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ["vib", "wave", id], queryFn: () => api<Wave>(`/vibration/events/${id}/waveform`) });
  if (q.isLoading) return <Loading />;
  if (!q.data?.available) return <Empty>{q.data?.reason}</Empty>;
  const w = q.data;
  const step = 2;
  const lim = Math.ceil(ppv * 1.1 * 10) / 10;
  return (
    <div className="space-y-1">
      {(["transverse", "vertical", "longitudinal"] as const).map((k) => {
        const data = w.t.filter((_, i) => i % step === 0).map((tt, i) => ({ t: tt, v: w[k][i * step] }));
        const peak = Math.max(...w[k].map(Math.abs));
        return (
          <div key={k}>
            <div className="flex justify-between text-[11px] text-fg-3"><span>{t(`vib.${k}`)}</span><span className="tnum">{t("vib.peak")} {fmtNum(peak, 2)} mm/s</span></div>
            <div className="h-16">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data} margin={{ top: 2, right: 4, left: -18, bottom: 0 }}>
                  <CartesianGrid stroke={chart.grid} vertical={false} />
                  <XAxis dataKey="t" type="number" domain={[0, 2]} hide={k !== "longitudinal"} {...axisProps} unit=" s" />
                  <YAxis domain={[-lim, lim]} {...axisProps} tickCount={3} />
                  <ReferenceLine y={0} stroke={chart.axis} />
                  <Line dataKey="v" stroke={chart.series[0]} dot={false} strokeWidth={1.2} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        );
      })}
      <p className="text-[10.5px] text-warning">{t("vib.simulatedWave", { fs: w.sample_rate_hz })}</p>
    </div>
  );
}

function QualityModal({ ev, onClose }: { ev: Ev; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [q, setQ] = useState(ev.data_quality);
  const [notes, setNotes] = useState(ev.quality_notes ?? "");
  const mut = useMutation({ mutationFn: () => send("PATCH", `/vibration/events/${ev.id}/quality`, { data_quality: q, quality_notes: notes }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["vib"] }); onClose(); } });
  return (
    <Modal title={`${t("vib.validate")} — ${ev.code}`} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button><Button perm="vibration.write" onClick={() => mut.mutate()} disabled={mut.isPending}>{t("common.save")}</Button></>}>
      <div className="space-y-3">
        <Field label={t("vib.quality")}><Select value={q} onChange={(e) => setQ(e.target.value)}>{["VALID", "QUESTIONABLE", "NO_TRIGGER", "INVALID"].map((x) => <option key={x} value={x}>{label(x)}</option>)}</Select></Field>
        <Field label={t("vib.qualityNotes")}><Textarea value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
        <p className="text-[11px] text-fg-3">{t("vib.qualityRule")}</p>
        <FormError error={mut.error} />
      </div>
    </Modal>
  );
}

function ImportModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [res, setRes] = useState<{ rows_ok: number; rows_rejected: number; errors: { row: number; error: string }[]; created: { code: string; compliance: string }[]; dry_run: boolean } | null>(null);
  const run = useMutation({
    mutationFn: (dry: boolean) => { const f = new FormData(); f.append("file", file!); return upload<NonNullable<typeof res>>(`/vibration/import?dry_run=${dry}`, f); },
    onSuccess: (r) => { setRes(r); if (!r.dry_run) qc.invalidateQueries({ queryKey: ["vib"] }); },
  });
  return (
    <Modal title={t("vib.importTitle")} onClose={onClose} wide
      footer={<><a href={withLang("/api/v1/vibration/import/sample.csv")} download className="mr-auto"><Button variant="ghost"><Download size={14} />{t("vib.sample")}</Button></a>
        <Button perm="vibration.write" variant="ghost" onClick={() => run.mutate(true)} disabled={!file || run.isPending}>{t("vib.validateOnly")}</Button>
        <Button perm="vibration.write" onClick={() => run.mutate(false)} disabled={!file || run.isPending || (res !== null && !res.dry_run)}><Upload size={14} />{t("vib.importNow")}</Button></>}>
      <div className="space-y-3">
        <Field label="CSV" hint={t("vib.importHint")}><Input type="file" accept=".csv,text/csv" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setRes(null); }} /></Field>
        {res && (
          <div className="space-y-2">
            <div className="flex gap-2"><Pill tone="good">{res.rows_ok} {t("vib.rowsOk")}</Pill><Pill tone={res.rows_rejected ? "critical" : "neutral"}>{res.rows_rejected} {t("vib.rowsRejected")}</Pill>
              {res.dry_run ? <Pill tone="info">{t("vib.dryRun")}</Pill> : <Pill tone="accent">{res.created.length} {t("vib.created")}</Pill>}</div>
            {res.errors.length > 0 && <ul className="text-[12.5px] max-h-40 overflow-y-auto scroll-thin">{res.errors.map((e) => <li key={e.row} className="border-b border-line-soft py-0.5"><span className="tnum text-fg-3">{t("vib.row")} {e.row}:</span> {e.error}</li>)}</ul>}
          </div>
        )}
        <FormError error={run.error} />
      </div>
    </Modal>
  );
}

export default function VibrationPage() {
  const { t } = useTranslation();
  const [station, setStation] = useState("V-03");
  const [filter, setFilter] = useState({ station: "", quality: "", compliance: "" });
  const [sel, setSel] = useState<Ev | null>(null);
  const [cmp, setCmp] = useState<number[]>([]);
  const [validate, setValidate] = useState<Ev | null>(null);
  const [imp, setImp] = useState(false);
  const stations = useQuery({ queryKey: ["vib", "stations"], queryFn: () => api<Station[]>("/vibration/stations") });
  const events = useQuery({ queryKey: ["vib", "events"], queryFn: () => api<Ev[]>("/vibration/events") });
  const all = events.data ?? [];
  const st = stations.data?.find((s) => s.code === station);
  const series = useMemo(() => all.filter((e) => e.station === station && e.ppv_mm_s !== null).map((e) => ({ ...e, ts: new Date(e.recorded_at).getTime() })).reverse(), [all, station]);
  const shown = all.filter((e) => (!filter.station || e.station === filter.station) && (!filter.quality || e.data_quality === filter.quality) && (!filter.compliance || e.compliance === filter.compliance));
  const compared = all.filter((e) => cmp.includes(e.id));
  const toggle = (id: number) => setCmp((c) => (c.includes(id) ? c.filter((x) => x !== id) : c.length >= 3 ? [...c.slice(1), id] : [...c, id]));

  return (
    <div className="space-y-4">
      <PageHeader title={t("vib.title")} subtitle={t("vib.subtitle")}
        right={<div className="flex gap-2"><a href={withLang(`/api/v1/vibration/report.csv${filter.station ? `?station=${filter.station}` : ""}`)} download><Button variant="ghost"><Download size={14} />{t("vib.report")}</Button></a>
          <Button perm="vibration.write" variant="ghost" onClick={() => setImp(true)}><Upload size={14} />{t("vib.import")}</Button></div>} />

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
        {stations.data?.map((s) => {
          const pct = s.max_ppv_30d && s.limit_ppv_mm_s ? (100 * s.max_ppv_30d) / s.limit_ppv_mm_s : 0;
          return (
            <button key={s.code} onClick={() => setStation(s.code)}
              className={clsx("text-left rounded-lg border bg-ink-800 p-3 hover:border-accent/60", station === s.code ? "border-accent" : s.exceedances ? "border-critical/50" : "border-line")}>
              <div className="flex justify-between items-start gap-2"><div><div className="font-mono text-sm">{s.code}</div><div className="text-[11px] text-fg-3 leading-tight">{s.name}</div></div>
                {s.exceedances > 0 ? <Pill tone="critical">{s.exceedances} {t("dashboard.exceedance")}</Pill> : <Pill tone="good">{t("vib.compliant")}</Pill>}</div>
              <div className="flex items-baseline gap-1 mt-2"><span className="text-2xl font-semibold tnum">{fmtNum(s.max_ppv_30d, 2)}</span><span className="text-xs text-fg-3">mm/s {t("vib.max30")}</span></div>
              <div className="flex items-center gap-2 mt-1"><Progress value={pct} max={100} tone={pct > 100 ? "critical" : pct > 70 ? "warning" : "info"} /><span className="text-[11px] tnum text-fg-3 w-24 text-right">{fmtNum(pct, 0)}% {t("vib.ofRef")}</span></div>
              <div className="flex flex-wrap gap-x-3 text-[11px] text-fg-3 mt-1.5">
                <span>{s.events_30d} {t("dashboard.events")} (30 d)</span><span>{fmtNum(s.valid_pct, 0)}% {t("vib.valid")}</span>
                {s.trend_slope_mm_s_per_event > 0.15 && <span className="text-warning flex items-center gap-0.5"><TrendingUp size={11} />{t("vib.rising")}</span>}
              </div>
            </button>
          );
        })}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Card title={t("vib.trendTitle", { station })} subtitle={st && `${t("vib.refValue")}: ${st.limit_ppv_mm_s} mm/s${st.limit_is_demo ? " · DEMO PLACEHOLDER" : ""} · ${st.instrument}`}>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart margin={{ top: 10, right: 16, left: -8, bottom: 0 }}>
                <CartesianGrid stroke={chart.grid} />
                <XAxis type="number" dataKey="ts" domain={["dataMin", "dataMax"]} {...axisProps} tickFormatter={(v) => fmtDate(new Date(v).toISOString().slice(0, 10))} />
                <YAxis type="number" dataKey="ppv_mm_s" {...axisProps} unit="" domain={[0, (m: number) => Math.max(12, Math.ceil(m + 1))]} />
                <ZAxis range={[46, 46]} />
                {st?.limit_ppv_mm_s && <ReferenceLine y={st.limit_ppv_mm_s} stroke={chart.reference} strokeDasharray="5 4" label={{ value: `${t("vib.refValue")} ${st.limit_ppv_mm_s} mm/s`, fill: chart.tick, fontSize: 10, position: "insideTopLeft" }} />}
                <Tooltip content={({ payload }) => { const e = payload?.[0]?.payload as Ev | undefined; return e ? <div className="recharts-default-tooltip px-2 py-1 text-xs"><div className="font-mono">{e.code}</div><div>{e.recorded_at.slice(0, 16).replace("T", " ")} · {fmtNum(e.ppv_mm_s, 2)} mm/s · {fmtNum(e.dominant_frequency_hz)} Hz · {label(e.compliance)}</div></div> : null; }} />
                <Scatter data={series} isAnimationActive={false} onClick={(p) => setSel(p as unknown as Ev)}>
                  {series.map((e) => <Cell key={e.id} fill={COMP_COLOR[e.compliance]} className="cursor-pointer" />)}
                </Scatter>
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <div className="flex gap-4 text-[11px] text-fg-2">{Object.entries(COMP_COLOR).map(([k, c]) => <span key={k} className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full" style={{ background: c }} />{label(k)}</span>)}<span className="text-fg-3">mm/s</span></div>
        </Card>
        <Card title={t("vib.ppvFreq")} subtitle={t("vib.ppvFreqSub")}>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart margin={{ top: 10, right: 16, left: -8, bottom: 10 }}>
                <CartesianGrid stroke={chart.grid} />
                <XAxis type="number" dataKey="dominant_frequency_hz" {...axisProps} scale="log" domain={[5, 100]} ticks={[5, 10, 20, 40, 100]} unit=" Hz" />
                <YAxis type="number" dataKey="ppv_mm_s" {...axisProps} domain={[0, (m: number) => Math.max(12, Math.ceil(m + 1))]} />
                <ZAxis range={[30, 30]} />
                {st?.limit_ppv_mm_s && <ReferenceLine y={st.limit_ppv_mm_s} stroke={chart.reference} strokeDasharray="5 4" />}
                <Tooltip content={({ payload }) => { const e = payload?.[0]?.payload as Ev | undefined; return e ? <div className="recharts-default-tooltip px-2 py-1 text-xs">{e.code}: {fmtNum(e.ppv_mm_s, 2)} mm/s @ {fmtNum(e.dominant_frequency_hz)} Hz</div> : null; }} />
                <Scatter data={series} isAnimationActive={false}>{series.map((e) => <Cell key={e.id} fill={COMP_COLOR[e.compliance]} />)}</Scatter>
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-1 2xl:grid-cols-[1fr_26rem] gap-4">
        <Card title={t("vib.events")} bodyClass="p-0" actions={
          <div className="flex gap-2">
            <Select className="text-xs py-1 max-w-[11rem]" value={filter.station} onChange={(e) => setFilter({ ...filter, station: e.target.value })} aria-label="station"><option value="">{t("vib.allStations")}</option>{stations.data?.map((s) => <option key={s.code}>{s.code}</option>)}</Select>
            <Select className="text-xs py-1 max-w-[11rem]" value={filter.quality} onChange={(e) => setFilter({ ...filter, quality: e.target.value })} aria-label="quality"><option value="">{t("vib.allQuality")}</option>{["VALID", "QUESTIONABLE", "NO_TRIGGER", "INVALID"].map((x) => <option key={x} value={x}>{label(x)}</option>)}</Select>
            <Select className="text-xs py-1 max-w-[11rem]" value={filter.compliance} onChange={(e) => setFilter({ ...filter, compliance: e.target.value })} aria-label="compliance"><option value="">{t("vib.allCompliance")}</option>{Object.keys(COMP_COLOR).map((x) => <option key={x} value={x}>{label(x)}</option>)}</Select>
          </div>}>
          {events.isLoading && <Loading />}
          <DataTable rows={shown} rowKey={(r) => r.id} selectedKey={sel?.id} onRowClick={setSel} columns={[
            { key: "cmp", header: t("vib.compare"), render: (r) => <input type="checkbox" checked={cmp.includes(r.id)} onClick={(e) => e.stopPropagation()} onChange={() => toggle(r.id)} aria-label={`compare ${r.code}`} /> },
            { key: "code", header: t("vib.event"), render: (r) => <span className="font-mono">{r.code}</span> },
            { key: "recorded_at", header: t("lab.date"), render: (r) => r.recorded_at.slice(0, 16).replace("T", " ") },
            { key: "station", header: "Station" },
            { key: "ppv_mm_s", header: "PPV (mm/s)", align: "right", render: (r) => fmtNum(r.ppv_mm_s, 2) },
            { key: "pct_of_limit", header: t("vib.pctRef"), align: "right", render: (r) => r.pct_of_limit !== null ? `${fmtNum(r.pct_of_limit, 0)}%` : "—" },
            { key: "dominant_frequency_hz", header: "Hz", align: "right", render: (r) => fmtNum(r.dominant_frequency_hz) },
            { key: "data_quality", header: t("vib.quality"), render: (r) => label(r.data_quality) },
            { key: "compliance", header: t("vib.compliance"), render: (r) => <Pill tone={COMP_TONE[r.compliance]}>{label(r.compliance)}</Pill> },
          ]} />
        </Card>
        <Card title={sel ? sel.code : t("vib.event")} actions={sel && <Button perm="vibration.write" variant="ghost" className="text-xs py-1 max-w-[11rem]" onClick={() => setValidate(sel)}>{t("vib.validate")}</Button>}>
          {!sel ? <Empty>{t("vib.selectEvent")}</Empty> : (
            <div className="space-y-3 text-[12.5px]">
              <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5 tnum">
                <dt className="text-fg-3">Station</dt><dd className="text-right">{sel.station} — {sel.station_name}</dd>
                <dt className="text-fg-3">{t("vib.blast")}</dt><dd className="text-right font-mono">{sel.blast ?? "—"}</dd>
                <dt className="text-fg-3">{t("vib.distance")}</dt><dd className="text-right">{fmtNum(sel.distance_m, 0)} m</dd>
                <dt className="text-fg-3">PPV T / V / L</dt><dd className="text-right">{fmtNum(sel.ppv_transverse, 2)} / {fmtNum(sel.ppv_vertical, 2)} / {fmtNum(sel.ppv_longitudinal, 2)}</dd>
                <dt className="text-fg-3">{t("vib.freq")}</dt><dd className="text-right">{fmtNum(sel.dominant_frequency_hz)} Hz</dd>
                <dt className="text-fg-3">{t("vib.aop")}</dt><dd className="text-right">{fmtNum(sel.air_overpressure_db)} dB(L)</dd>
                <dt className="text-fg-3">{t("vib.quality")}</dt><dd className="text-right">{label(sel.data_quality)}</dd>
                <dt className="text-fg-3">{t("vib.compliance")}</dt><dd className="text-right"><Pill tone={COMP_TONE[sel.compliance]}>{label(sel.compliance)}</Pill></dd>
              </dl>
              {sel.quality_notes && <p className="text-fg-2 border-l-2 border-line pl-2">{sel.quality_notes}</p>}
              {sel.ppv_mm_s !== null ? <Waveforms id={sel.id} ppv={sel.ppv_mm_s} /> : <Empty>{t("vib.noWave")}</Empty>}
            </div>
          )}
        </Card>
      </div>

      {compared.length > 0 && (
        <Card title={t("vib.comparison", { n: compared.length })} bodyClass="p-0 overflow-x-auto">
          <table className="w-full text-[12.5px] tnum">
            <thead className="text-[11px] uppercase text-fg-3"><tr className="border-b border-line-soft"><th className="text-left px-3 py-2" />{compared.map((e) => <th key={e.id} className="text-right px-3 font-mono normal-case">{e.code}</th>)}</tr></thead>
            <tbody>
              {([["Station", (e: Ev) => e.station], [t("lab.date"), (e: Ev) => e.recorded_at.slice(0, 10)], [t("vib.blast"), (e: Ev) => e.blast ?? "—"],
                [t("vib.distance"), (e: Ev) => `${fmtNum(e.distance_m, 0)} m`], ["PPV", (e: Ev) => `${fmtNum(e.ppv_mm_s, 2)} mm/s`],
                [t("vib.pctRef"), (e: Ev) => (e.pct_of_limit !== null ? `${fmtNum(e.pct_of_limit, 0)}%` : "—")], [t("vib.freq"), (e: Ev) => `${fmtNum(e.dominant_frequency_hz)} Hz`],
                [t("vib.aop"), (e: Ev) => `${fmtNum(e.air_overpressure_db)} dB(L)`], [t("vib.quality"), (e: Ev) => label(e.data_quality)], [t("vib.compliance"), (e: Ev) => label(e.compliance)]] as [string, (e: Ev) => string][]).map(([k, f]) => (
                <tr key={k} className="border-b border-line-soft last:border-0"><td className="px-3 py-1.5 text-fg-3">{k}</td>{compared.map((e) => <td key={e.id} className="px-3 text-right">{f(e)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      <p className="text-[11px] text-fg-3">{t("vib.limitNote")}</p>
      {validate && <QualityModal ev={validate} onClose={() => { setValidate(null); setSel(null); }} />}
      {imp && <ImportModal onClose={() => setImp(false)} />}
    </div>
  );
}
