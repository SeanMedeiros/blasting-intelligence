import { useQuery } from "@tanstack/react-query";
import { FileDown, FileSpreadsheet } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Card } from "../../components/ui";
import { Input, Select } from "../../components/ui/forms";
import { api, withLang } from "../../lib/api";
import { addDays, lastMonths, useToday } from "../../lib/dates";

type Opt = { value: string; label: string };

export default function ReportGenerator() {
  const { t } = useTranslation();
  const blasts = useQuery({ queryKey: ["blasts", "board"], queryFn: () => api<{ blasts: { id: number; code: string; status: string }[] }>("/blasts") });
  const surveys = useQuery({ queryKey: ["surveys"], queryFn: () => api<{ id: number; code: string; survey_type: string }[]>("/surveys") });
  const patterns = useQuery({ queryKey: ["dh", "patterns"], queryFn: () => api<{ id: number; code: string }[]>("/drillholes/patterns") });
  const today = useToday();
  const months = lastMonths(today, 12);
  const [p, setP] = useState<Record<string, string>>({ day: today, start: addDays(today, -29), end: today, month: months[months.length - 2], blast_id: "", survey_id: "", pattern_id: "" });
  const opts: Record<string, Opt[]> = {
    blast_id: (blasts.data?.blasts ?? []).filter((b) => !["PLANNED"].includes(b.status)).map((b) => ({ value: String(b.id), label: `${b.code} · ${b.status}` })),
    survey_id: (surveys.data ?? []).map((s) => ({ value: String(s.id), label: `${s.code}` })),
    pattern_id: (patterns.data ?? []).map((x) => ({ value: String(x.id), label: x.code })),
  };
  const val = (k: string) => p[k] || opts[k]?.[0]?.value || "";
  const reports: { key: string; params: string[] }[] = [
    { key: "daily", params: ["day"] }, { key: "blast", params: ["blast_id"] }, { key: "survey", params: ["survey_id"] }, { key: "drillholes", params: ["pattern_id"] },
    { key: "laboratory", params: ["start", "end"] }, { key: "vibration", params: ["start", "end"] }, { key: "qaqc", params: ["start", "end"] }, { key: "kpi-monthly", params: ["month"] },
  ];
  const qs = (ps: string[]) => ps.map((k) => `${k}=${encodeURIComponent(val(k))}`).join("&");
  return (
    <Card title={t("reports.generator")} subtitle={t("reports.generatorSub")} bodyClass="p-0">
      <ul className="divide-y divide-line-soft">
        {reports.map((r) => (
          <li key={r.key} className="px-4 py-2.5 flex flex-wrap items-center gap-3">
            <div className="w-56"><div className="text-sm">{t(`reports.types.${r.key}.t`)}</div><div className="text-[11px] text-fg-3">{t(`reports.types.${r.key}.d`)}</div></div>
            <div className="flex flex-wrap gap-2 flex-1">
              {r.params.map((k) => opts[k] ? (
                <Select key={k} value={val(k)} onChange={(e) => setP({ ...p, [k]: e.target.value })} className="max-w-[16rem] text-xs py-1" aria-label={k}>
                  {opts[k].map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </Select>
              ) : k === "month" ? (
                <Input key={k} type="month" value={p.month} min={months[0]} max={months[months.length - 1]} onChange={(e) => setP({ ...p, month: e.target.value })} className="max-w-[10rem] text-xs py-1" aria-label={k} />
              ) : (
                <Input key={k} type="date" value={p[k]} onChange={(e) => setP({ ...p, [k]: e.target.value })} className="max-w-[10rem] text-xs py-1" aria-label={k} />
              ))}
            </div>
            <a href={withLang(`/api/v1/reports/${r.key}.pdf?${qs(r.params)}`)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded bg-accent text-ink-950 px-2.5 py-1 text-xs font-semibold hover:bg-accent/90"><FileDown size={13} />PDF</a>
            <a href={withLang(`/api/v1/reports/${r.key}.csv?${qs(r.params)}`)} download className="inline-flex items-center gap-1 rounded border border-line px-2.5 py-1 text-xs text-fg-2 hover:text-fg hover:border-accent"><FileSpreadsheet size={13} />CSV</a>
          </li>
        ))}
      </ul>
    </Card>
  );
}
