import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, LabelList, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { axisProps, chart } from "../../components/charts/theme";
import { Card, Empty, ErrorState, Loading, PageHeader, Pill, Progress, StatusPill } from "../../components/ui";
import { api, type Dashboard } from "../../lib/api";
import { fmtDate, fmtNum, label } from "../../lib/format";
import KpiTiles from "./KpiTiles";
import SetupCard from "./SetupCard";

const MODULE_PATH: Record<string, string> = {
  laboratory: "/laboratory", drillholes: "/drillholes", scanning: "/scanning", vibration: "/vibration", safety: "/safety",
  postblast: "/postblast", planning: "/planning", reports: "/reports", settings: "/settings",
};

export default function DashboardPage() {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dashboard>("/dashboard") });
  if (q.isLoading) return <Loading />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data;

  const devTrend = d.kpi_trend.labels.map((l, i) => ({ label: l.replace(/^\d{4}-/, ""), v: d.kpi_trend.series.drillhole_deviation_rate?.[i] ?? null }));
  const devTarget = d.kpis.find((k) => k.key === "drillhole_deviation_rate")?.target ?? undefined;
  const vib = d.vibration.map((v) => ({ ...v, label: v.station }));
  const vibLimit = d.vibration.find((v) => v.limit)?.limit ?? undefined;

  return (
    <div className="space-y-4">
      <PageHeader title={t("dashboard.title")} subtitle={t("dashboard.subtitle")} />
      <SetupCard />

      <section aria-label={t("dashboard.kpis")}>
        <div className="flex items-baseline justify-between mb-2">
          <h2 className="text-[13px] font-semibold uppercase tracking-wide">{t("dashboard.kpis")}</h2>
          <span className="text-xs text-fg-3">{t("dashboard.kpiHint")}</span>
        </div>
        <KpiTiles kpis={d.kpis} trend={d.kpi_trend} />
      </section>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {/* Today */}
        <Card title={t("dashboard.today")} bodyClass="p-0">
          <ul className="divide-y divide-line-soft max-h-80 overflow-y-auto scroll-thin">
            {d.activities.length === 0 && <Empty>{t("common.none")}</Empty>}
            {d.activities.map((a) => (
              <li key={a.id} className="px-4 py-2 flex items-center gap-3 text-sm">
                <div className="min-w-0 flex-1">
                  <div className="text-fg truncate">{label(a.activity)}</div>
                  <div className="text-[11px] text-fg-3 truncate">
                    {a.work_order} · {a.responsible ?? "—"}
                    {a.planned_date !== d.today && <span className="text-serious"> · {fmtDate(a.planned_date)} ({t("dashboard.carryOver")})</span>}
                  </div>
                </div>
                <StatusPill status={a.status} />
              </li>
            ))}
          </ul>
        </Card>

        {/* Blast pipeline */}
        <Card title={t("dashboard.blasts")} bodyClass="p-0">
          <ul className="divide-y divide-line-soft">
            {d.pending_blasts.map((b) => {
              const v = b.verification;
              return (
                <li key={b.code} className="px-4 py-2.5 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <span className="font-medium font-mono text-[13px]">{b.code}</span>
                      <span className="text-fg-3 text-xs"> · {b.bench} · {fmtDate(b.planned_date)}</span>
                    </div>
                    <StatusPill status={b.status} />
                  </div>
                  <div className="mt-1.5 flex items-center gap-2 text-[11px] text-fg-3">
                    <span className="w-24 shrink-0">{t("dashboard.verification")}</span>
                    <Progress value={v.measured} max={v.holes} tone={v.measured === v.holes ? "good" : "info"} />
                    <span className="tnum w-14 text-right">{v.measured}/{v.holes}</span>
                  </div>
                  {v.out_of_tolerance > 0 && (
                    <div className="text-[11px] text-serious mt-0.5">{v.out_of_tolerance} {t("dashboard.outOfTol")}</div>
                  )}
                  {b.authorization_ref && (
                    <div className="text-[11px] text-fg-3 mt-0.5">
                      {t("dashboard.authRef")}: <span className="font-mono text-fg-2">{b.authorization_ref}</span>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
          <div className="px-4 py-2 border-t border-line-soft flex flex-wrap gap-1.5">
            {Object.entries(d.blast_status_counts).map(([s, n]) => (
              <span key={s} className="text-[11px] text-fg-3">
                {label(s)} <span className="text-fg tnum">{n}</span>
              </span>
            )).reduce<ReactNode[]>((acc, el, i) => (i ? [...acc, <span key={`s${i}`} className="text-fg-3">·</span>, el] : [el]), [])}
          </div>
        </Card>

        {/* Alerts */}
        <Card title={t("dashboard.alerts")} subtitle={t("dashboard.alertsHint")} bodyClass="p-0">
          <ul className="divide-y divide-line-soft max-h-[26rem] overflow-y-auto scroll-thin">
            {d.alerts.map((a, i) => (
              <li key={i} className="px-4 py-2.5">
                <div className="flex items-start gap-2">
                  <StatusPill status={a.severity} text={label(a.severity)} />
                  <div className="min-w-0 flex-1">
                    <Link to={MODULE_PATH[a.module] ?? "/"} className="text-sm text-fg hover:text-accent flex items-center gap-1">
                      {a.title} <ChevronRight size={13} className="text-fg-3" />
                    </Link>
                    <p className="text-[11.5px] text-fg-3 mt-0.5">{a.detail}</p>
                    <p className="text-[10.5px] text-fg-3/80 font-mono mt-0.5 truncate" title={a.refs.join(", ")}>
                      {a.rule} · {a.refs.slice(0, 4).join(", ")}{a.refs.length > 4 ? ` +${a.refs.length - 4}` : ""}
                    </p>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {/* Vibration */}
        <Card title={t("dashboard.vibration")} subtitle={`--- ${t("dashboard.vibrationRef")}`}>
          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={vib} margin={{ top: 16, right: 8, left: -12, bottom: 0 }} barCategoryGap="30%">
                <CartesianGrid stroke={chart.grid} vertical={false} />
                <XAxis dataKey="label" {...axisProps} />
                <YAxis {...axisProps} unit="" domain={[0, (max: number) => Math.max(12, Math.ceil(max + 1))]} />
                <Tooltip
                  cursor={{ fill: "#ffffff08" }}
                  formatter={(v, _n, p) => [`${fmtNum(v as number, 2)} mm/s (${(p.payload as { valid: number }).valid} valid events)`, "Max PPV"]}
                  labelFormatter={(l, p) => (p?.[0]?.payload as { name: string })?.name ?? l}
                />
                {vibLimit && <ReferenceLine y={vibLimit} stroke={chart.reference} strokeDasharray="5 4" />}
                <Bar dataKey="max_ppv" radius={[4, 4, 0, 0]} isAnimationActive={false}>
                  {vib.map((v) => (
                    <Cell key={v.station} fill={v.exceedances ? chart.critical : chart.series[0]} />
                  ))}
                  <LabelList dataKey="max_ppv" position="top" fill={chart.text} fontSize={11} formatter={(v) => fmtNum(v as number, 1)} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="flex flex-wrap gap-2 mt-2">
            {d.vibration.filter((v) => v.exceedances).map((v) => (
              <Pill key={v.station} tone="critical">{v.station}: {v.exceedances} {t("dashboard.exceedance")}</Pill>
            ))}
            <span className="text-[11px] text-fg-3">mm/s · {d.vibration.reduce((a, v) => a + v.events, 0)} {t("dashboard.events")}</span>
          </div>
        </Card>

        {/* Lab */}
        <Card title={t("dashboard.lab")}>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-semibold">{d.laboratory.tests}</span>
            <span className="text-sm text-fg-3">{t("dashboard.tests")}</span>
          </div>
          <div className="flex flex-wrap gap-1.5 mt-2">
            {Object.entries(d.laboratory.by_result).map(([r, n]) => (
              <StatusPill key={r} status={r} text={`${label(r)} · ${n}`} />
            ))}
          </div>
          <table className="w-full text-sm mt-3">
            <tbody>
              {Object.entries(d.laboratory.by_type).map(([k, n]) => (
                <tr key={k} className="border-t border-line-soft">
                  <td className="py-1 text-fg-2">{label(k)}</td>
                  <td className="py-1 text-right tnum">{n}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-3 text-sm flex flex-wrap items-center gap-2">
            <Pill tone={d.laboratory.open_nonconformances ? "warning" : "good"}>
              {d.laboratory.open_nonconformances} {t("dashboard.openNc")}
            </Pill>
          </div>
          {d.laboratory.quarantined_batches.length > 0 && (
            <div className="mt-2 text-[11.5px] text-fg-3">
              {t("dashboard.quarantine")}: <span className="font-mono text-fg-2">{d.laboratory.quarantined_batches.join(", ")}</span>
            </div>
          )}
        </Card>

        {/* Safety */}
        <Card title={t("dashboard.safety")}>
          <div className="grid grid-cols-3 gap-3 text-center">
            <div>
              <div className="text-3xl font-semibold">{d.safety.open_observations}</div>
              <div className="text-[11px] text-fg-3">{t("dashboard.openObs")}</div>
            </div>
            <div>
              <div className="text-3xl font-semibold">{d.safety.open_capa}</div>
              <div className="text-[11px] text-fg-3">{t("dashboard.openCapa")}</div>
              {d.safety.overdue_capa > 0 && <div className="text-[11px] text-critical">{d.safety.overdue_capa} {t("dashboard.overdue")}</div>}
            </div>
            <div>
              <div className="text-3xl font-semibold">{d.safety.near_misses_30d}</div>
              <div className="text-[11px] text-fg-3">{t("dashboard.nearMiss")}</div>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-1.5">
            {(["CRITICAL", "HIGH", "MEDIUM", "LOW"] as const).map((r) => (
              <StatusPill key={r} status={r} text={`${label(r)} · ${d.safety.open_by_risk[r] ?? 0}`} />
            ))}
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {/* Deliveries */}
        <Card title={t("dashboard.deliveries")} className="xl:col-span-2" bodyClass="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-[11px] uppercase text-fg-3 tracking-wide">
              <tr className="border-b border-line-soft">
                <th className="text-left font-medium px-4 py-2">{t("dashboard.cols.code")}</th>
                <th className="text-left font-medium px-2 py-2">{t("dashboard.cols.product")}</th>
                <th className="text-left font-medium px-2 py-2">{t("dashboard.cols.area")}</th>
                <th className="text-right font-medium px-2 py-2">{t("dashboard.cols.planned")}</th>
                <th className="text-right font-medium px-2 py-2">{t("dashboard.cols.qty")}</th>
                <th className="text-left font-medium px-4 py-2">{t("dashboard.cols.status")}</th>
              </tr>
            </thead>
            <tbody>
              {d.deliveries.map((x) => (
                <tr key={x.code} className="border-b border-line-soft last:border-0">
                  <td className="px-4 py-1.5 font-mono text-[12.5px]">{x.code}</td>
                  <td className="px-2 py-1.5 text-fg-2 truncate max-w-[16rem]">{x.product}</td>
                  <td className="px-2 py-1.5">{x.area}</td>
                  <td className="px-2 py-1.5 text-right tnum">{fmtDate(x.planned_date)}</td>
                  <td className="px-2 py-1.5 text-right tnum">
                    {x.delivered_qty !== null ? `${fmtNum(x.delivered_qty)} / ` : ""}{fmtNum(x.planned_qty)}
                  </td>
                  <td className="px-4 py-1.5"><StatusPill status={x.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        {/* Equipment */}
        <Card title={t("dashboard.equipment")} bodyClass="p-0">
          <ul className="divide-y divide-line-soft">
            {d.equipment.map((e) => (
              <li key={e.code} className="px-4 py-1.5 flex items-center gap-3 text-sm">
                <span className="font-mono text-[12.5px] w-16">{e.code}</span>
                <div className="flex-1"><Progress value={e.availability_30d} max={100} tone={e.availability_30d < 85 ? "warning" : "good"} /></div>
                <span className="tnum text-xs w-12 text-right">{fmtNum(e.availability_30d)}%</span>
                <StatusPill status={e.status} />
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <Card title={t("dashboard.trendTitle")} subtitle={t("dashboard.trendNote")} className="xl:col-span-2">
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={devTrend} margin={{ top: 8, right: 16, left: -12, bottom: 0 }}>
                <CartesianGrid stroke={chart.grid} vertical={false} />
                <XAxis dataKey="label" {...axisProps} />
                <YAxis {...axisProps} unit="%" />
                <Tooltip formatter={(v) => [`${fmtNum(v as number)} %`, t("kpiNames.drillhole_deviation_rate")]} />
                {devTarget !== undefined && (
                  <ReferenceLine y={devTarget} stroke={chart.reference} strokeDasharray="5 4"
                    label={{ value: `${t("common.target")} ≤ ${devTarget}% (${t("common.demoTarget")})`, fill: chart.tick, fontSize: 11, position: "insideTopRight" }} />
                )}
                <Line type="linear" dataKey="v" stroke={chart.series[0]} strokeWidth={2} dot={{ r: 3, strokeWidth: 0, fill: chart.series[0] }} activeDot={{ r: 5 }} connectNulls isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card title={t("dashboard.surveys")}>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(d.surveys.last_30d).map(([s, n]) => (
              <StatusPill key={s} status={s} text={`${label(s)} · ${n}`} />
            ))}
          </div>
          <div className="mt-4 text-[12px] text-fg-3">{t("dashboard.missingPost")}</div>
          <div className="mt-1 font-mono text-sm">
            {d.surveys.missing_post_blast.length ? d.surveys.missing_post_blast.join(", ") : <span className="text-good">{t("common.none")}</span>}
          </div>
        </Card>
      </div>
    </div>
  );
}
