import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileDown, Info, Pencil } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useCan } from "../../auth/context";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { axisProps, chart } from "../../components/charts/theme";
import { Card, Loading, PageHeader, Pill, StatusPill } from "../../components/ui";
import { Button, Field, FormError, Input, Modal, Select } from "../../components/ui/forms";
import { Stat } from "../../components/ui/table";
import { api, send, type Kpi, withLang } from "../../lib/api";
import { fmtNum } from "../../lib/format";
import { KpiDetail } from "../dashboard/KpiTiles";
import { addDays, firstOfMonth, lastMonths, useToday, weekStart } from "../../lib/dates";

const monthRange = (mth: string) => {
  const [y, m] = mth.split("-").map(Number);
  const last = new Date(y, m, 0).getDate();
  return { start: `${mth}-01`, end: `${mth}-${String(last).padStart(2, "0")}` };
};
const prevMonth = (mth: string) => { const [y, m] = mth.split("-").map(Number); return m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, "0")}`; };

function TargetModal({ k, onClose }: { k: Kpi; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [f, setF] = useState({ target: String(k.target ?? ""), source: "" });
  const mut = useMutation({ mutationFn: () => send("PUT", `/kpis/targets/${k.key}`, { target: Number(f.target), source: f.source }), onSuccess: () => { qc.invalidateQueries(); onClose(); } });
  return (
    <Modal title={`${t("kpi.setTarget")} — ${t(`kpiNames.${k.key}`)}`} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button><Button perm="config.targets" onClick={() => mut.mutate()} disabled={f.source.length < 3}>{t("common.save")}</Button></>}>
      <div className="space-y-3">
        <Field label={`${t("common.target")} (${k.unit}) — ${k.direction === "LOWER" ? t("settings.lower") : t("settings.higher")}`}><Input type="number" value={f.target} onChange={(e) => setF({ ...f, target: e.target.value })} /></Field>
        <Field label={t("kpi.targetSource")} hint={t("kpi.targetSourceHint")}><Input value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })} /></Field>
        <FormError error={mut.error} />
      </div>
    </Modal>
  );
}

export default function KpiPage() {
  const { t } = useTranslation();
  const can = useCan();
  const today = useToday();
  const MONTHS = lastMonths(today, 6);
  const [month, setMonth] = useState(MONTHS[MONTHS.length - 2]);  // last complete month
  const [gran, setGran] = useState<"month" | "week" | "day">("month");
  const [detailKey, setDetail] = useState<string | null>(null);
  const [edit, setEdit] = useState<Kpi | null>(null);
  const r = monthRange(month);
  const p = monthRange(prevMonth(month));
  const cur = useQuery({ queryKey: ["kpi", r.start], queryFn: () => api<Kpi[]>("/kpis", r) });
  const detail = cur.data?.find((x) => x.key === detailKey) ?? null;
  const prev = useQuery({ queryKey: ["kpi", p.start], queryFn: () => api<Kpi[]>("/kpis", p), enabled: month !== MONTHS[0] });
  const range = gran === "day" ? { start: addDays(today, -29), end: today } : gran === "week" ? { start: weekStart(addDays(today, -119)), end: today } : { start: firstOfMonth(MONTHS[0]), end: today };
  const series = useQuery({ queryKey: ["kpi", "series", gran, today], queryFn: () => api<{ labels: string[]; series: Record<string, (number | null)[]> }>("/kpis/series", { granularity: gran, ...range }) });
  const k = cur.data ?? [];
  const prevMap = Object.fromEntries((prev.data ?? []).map((x) => [x.key, x.value]));
  const on = k.filter((x) => x.status === "ON_TARGET").length;
  const off = k.filter((x) => x.status === "OFF_TARGET").length;
  const partial = r.end > today;
  const demoTargets = k.some((x) => x.target_is_demo);

  return (
    <div className="space-y-4">
      <PageHeader title={t("kpi.title")} subtitle={t("kpi.subtitle")} right={
        <div className="flex gap-2 items-center">
          <Select value={month} onChange={(e) => setMonth(e.target.value)} className="max-w-[10rem] py-1" aria-label={t("kpi.month")}>{MONTHS.map((m) => <option key={m} value={m}>{m}{m === MONTHS[MONTHS.length - 1] ? ` (${t("kpi.mtd")})` : ""}</option>)}</Select>
          <a href={withLang(`/api/v1/reports/kpi-monthly.pdf?month=${month}`)} target="_blank" rel="noreferrer"><Button><FileDown size={14} />{t("kpi.monthlyPdf")}</Button></a>
          <a href={withLang(`/api/v1/reports/kpi-monthly.csv?month=${month}`)} download><Button variant="ghost">CSV</Button></a>
        </div>} />
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label={t("kpi.period")} value={<span className="text-lg">{r.start} → {partial ? today : r.end}</span>} sub={partial ? t("kpi.mtd") : undefined} />
        <Stat label={t("kpi.onTarget")} value={`${on} / ${k.length}`} tone="good" />
        <Stat label={t("kpi.offTarget")} value={off} tone={off ? "critical" : undefined} />
        {demoTargets && <Stat label={t("kpi.demoNote")} value={<Pill tone="warning">DEMO</Pill>} sub={t("kpi.demoSub")} />}
      </div>
      <Card title={t("kpi.table")} bodyClass="p-0 overflow-x-auto">
        {cur.isLoading ? <Loading /> : (
          <table className="w-full text-[12.5px] tnum">
            <thead className="text-[11px] uppercase text-fg-3"><tr className="border-b border-line-soft">
              {["#", t("settings.kpi"), t("kpi.actual"), t("common.target"), t("kpi.prev"), "Δ", t("kpi.numDen"), t("lab.status"), ""].map((h, i) => <th key={i} className={`px-3 py-2 font-medium ${i >= 2 && i <= 6 ? "text-right" : "text-left"}`}>{h}</th>)}
            </tr></thead>
            <tbody>
              {k.map((x, i) => {
                const pv = prevMap[x.key];
                const delta = x.value !== null && pv !== null && pv !== undefined ? x.value - pv : null;
                const better = delta === null || Math.abs(delta) < 1e-9 ? null : x.direction === "LOWER" ? delta < 0 : delta > 0;
                return (
                  <tr key={x.key} className="border-b border-line-soft last:border-0 hover:bg-ink-750">
                    <td className="px-3 py-1.5 text-fg-3">{i + 1}</td>
                    <td className="px-3 py-1.5">{t(`kpiNames.${x.key}`)}</td>
                    <td className="px-3 py-1.5 text-right font-semibold">{fmtNum(x.value)} {x.unit}</td>
                    <td className="px-3 py-1.5 text-right">{x.target === null ? <span className="text-fg-3">{t("kpi.noTarget")}</span> : <>{x.direction === "LOWER" ? "≤" : "≥"} {fmtNum(x.target)}</>}{x.target_is_demo && <span className="text-warning text-[10px] ml-1">DEMO</span>}</td>
                    <td className="px-3 py-1.5 text-right text-fg-2">{fmtNum(pv)}</td>
                    <td className={`px-3 py-1.5 text-right ${better === null ? "" : better ? "text-good" : "text-critical"}`}>{delta === null ? "—" : `${delta > 0 ? "+" : ""}${fmtNum(delta)}`}</td>
                    <td className="px-3 py-1.5 text-right text-fg-3">{fmtNum(x.numerator)} / {fmtNum(x.denominator)}</td>
                    <td className="px-3 py-1.5"><StatusPill status={x.status} /></td>
                    <td className="px-3 py-1.5 whitespace-nowrap">
                      <button className="text-fg-3 hover:text-accent mr-2" onClick={() => setDetail(x.key)} aria-label={t("common.formula")}><Info size={14} /></button>
                      {can("config.targets") && <button className="text-fg-3 hover:text-accent" onClick={() => setEdit(x)} aria-label={t("kpi.setTarget")}><Pencil size={14} /></button>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>
      <Card title={t("kpi.trends")} subtitle={t("kpi.trendsSub")} actions={
        <Select value={gran} onChange={(e) => setGran(e.target.value as typeof gran)} className="max-w-[12rem] text-xs py-1" aria-label={t("kpi.granularity")}>
          <option value="month">{t("kpi.monthly")}</option><option value="week">{t("kpi.weekly")}</option><option value="day">{t("kpi.daily")}</option>
        </Select>}>
        {!series.data ? <Loading /> : (
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-5 gap-3">
            {k.map((x) => {
              const data = series.data!.labels.map((l, i) => ({ l: gran === "month" ? l : l.slice(5), v: series.data!.series[x.key]?.[i] ?? null }));
              return (
                <div key={x.key} className="rounded border border-line-soft p-2">
                  <div className="text-[11.5px] text-fg-2 truncate" title={t(`kpiNames.${x.key}`)}>{t(`kpiNames.${x.key}`)}</div>
                  <div className="h-28">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={data} margin={{ top: 6, right: 6, left: -22, bottom: 0 }}>
                        <CartesianGrid stroke={chart.grid} vertical={false} />
                        <XAxis dataKey="l" {...axisProps} tick={{ fill: chart.tick, fontSize: 9 }} interval="preserveStartEnd" />
                        <YAxis {...axisProps} tick={{ fill: chart.tick, fontSize: 9 }} domain={x.unit === "%" ? [(mn: number) => Math.max(0, Math.floor(Math.min(mn, x.target ?? mn) - 5)), (mx: number) => Math.min(100, Math.ceil(Math.max(mx, x.target ?? mx) + 2))] : ["auto", "auto"]} />
                        {x.target !== null && <ReferenceLine y={x.target} stroke={chart.reference} strokeDasharray="4 3" />}
                        <Tooltip formatter={(v) => [`${fmtNum(v as number)} ${x.unit}`, ""]} separator="" />
                        <Line type="linear" dataKey="v" stroke={chart.series[0]} strokeWidth={2} dot={{ r: gran === "day" ? 0 : 2.5, fill: chart.series[0], strokeWidth: 0 }} connectNulls isAnimationActive={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>
      {detail && <KpiDetail kpi={detail} onClose={() => setDetail(null)} />}
      {edit && <TargetModal k={edit} onClose={() => setEdit(null)} />}
    </div>
  );
}
