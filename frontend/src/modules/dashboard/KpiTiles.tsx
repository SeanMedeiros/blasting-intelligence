import clsx from "clsx";
import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Line, LineChart, ResponsiveContainer, Tooltip, YAxis } from "recharts";
import { chart } from "../../components/charts/theme";
import { StatusPill } from "../../components/ui";
import type { Kpi } from "../../lib/api";
import { fmtNum } from "../../lib/format";

function Sparkline({ data }: { data: { label: string; v: number | null }[] }) {
  return (
    <div className="h-9 w-full" aria-hidden>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 2, bottom: 2, left: 2 }}>
          <YAxis hide domain={["auto", "auto"]} />
          <Tooltip
            cursor={{ stroke: chart.axis }}
            formatter={(v) => [fmtNum(v as number), ""]}
            labelFormatter={(_, p) => (p?.[0]?.payload as { label: string })?.label ?? ""}
            contentStyle={{ padding: "4px 8px" }}
            separator=""
          />
          <Line type="linear" dataKey="v" stroke={chart.series[0]} strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function KpiDetail({ kpi, onClose }: { kpi: Kpi; onClose: () => void }) {
  const { t } = useTranslation();
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose} role="dialog" aria-modal="true" aria-label={kpi.name}>
      <div className="w-full max-w-lg rounded-lg border border-line bg-ink-800 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between px-5 py-4 border-b border-line">
          <div>
            <div className="text-xs text-fg-3 uppercase tracking-wide">{t("common.formula")}</div>
            <h3 className="text-lg font-semibold">{t(`kpiNames.${kpi.key}`)}</h3>
          </div>
          <button onClick={onClose} className="text-fg-3 hover:text-fg" aria-label={t("common.close")}>
            <X size={18} />
          </button>
        </div>
        <div className="p-5 space-y-4 text-sm">
          <p className="rounded bg-ink-900 border border-line-soft p-3 font-mono text-[12.5px] leading-relaxed text-fg-2">{kpi.formula}</p>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
            <dt className="text-fg-3">{kpi.unit === "h" ? "Hours" : t("common.numerator")}</dt>
            <dd className="tnum text-right">{fmtNum(kpi.numerator, 1)}</dd>
            <dt className="text-fg-3">{kpi.unit === "h" ? "Delay events" : t("common.denominator")}</dt>
            <dd className="tnum text-right">{fmtNum(kpi.denominator, 1)}</dd>
            <dt className="text-fg-3">Result</dt>
            <dd className="tnum text-right font-semibold">{fmtNum(kpi.value)} {kpi.unit}</dd>
            <dt className="text-fg-3">{t("common.target")}</dt>
            <dd className="tnum text-right">
              {kpi.target === null ? t("kpi.noTarget") : `${kpi.direction === "LOWER" ? "≤" : "≥"} ${fmtNum(kpi.target)} ${kpi.unit}`}
              {kpi.target_is_demo && <span className="block text-[11px] text-warning">{t("common.demoTarget")}</span>}
            </dd>
            <dt className="text-fg-3">{t("common.period")}</dt>
            <dd className="tnum text-right">{kpi.period.start} → {kpi.period.end}</dd>
          </dl>
          <div className="flex justify-end"><StatusPill status={kpi.status} /></div>
        </div>
      </div>
    </div>
  );
}

export default function KpiTiles({ kpis, trend }: { kpis: Kpi[]; trend: { labels: string[]; series: Record<string, (number | null)[]> } }) {
  const { t } = useTranslation();
  const [selKey, setSel] = useState<string | null>(null);
  const sel = kpis.find((k) => k.key === selKey) ?? null;  // follows refetches (e.g. language change)
  return (
    <>
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 2xl:grid-cols-7 gap-3">
        {kpis.map((k) => {
          const data = trend.labels.map((l, i) => ({ label: l, v: trend.series[k.key]?.[i] ?? null }));
          return (
            <button
              key={k.key}
              onClick={() => setSel(k.key)}
              className={clsx(
                "text-left rounded-lg border bg-ink-800 p-3 hover:border-accent/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent transition-colors",
                k.status === "OFF_TARGET" ? "border-critical/40" : "border-line",
              )}
            >
              <div className="text-[11.5px] text-fg-2 leading-tight min-h-[2.4em]">{t(`kpiNames.${k.key}`)}</div>
              <div className="flex items-baseline gap-1 mt-1">
                <span className="text-2xl font-semibold text-fg">{fmtNum(k.value)}</span>
                <span className="text-xs text-fg-3">{k.unit}</span>
              </div>
              <div className="text-[11px] text-fg-3 tnum">
                {k.target === null ? t("kpi.noTarget") : <>{t("common.target")} {k.direction === "LOWER" ? "≤" : "≥"} {fmtNum(k.target)}{k.unit === "%" ? "%" : ` ${k.unit}`}</>}
              </div>
              <Sparkline data={data} />
              <StatusPill status={k.status} />
            </button>
          );
        })}
      </div>
      {sel && <KpiDetail kpi={sel} onClose={() => setSel(null)} />}
    </>
  );
}
