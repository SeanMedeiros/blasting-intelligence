import { keepPreviousData, useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Download, Search } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Card, ErrorState, Loading, PageHeader } from "../../components/ui";
import { api } from "../../lib/api";
import ReportGenerator from "./ReportGenerator";

interface RecordType { name: string; count: number; columns: string[] }
interface Page { total: number; limit: number; offset: number; items: Record<string, unknown>[] }

const PAGE = 50;

function toCsv(rows: Record<string, unknown>[], cols: string[]) {
  const esc = (v: unknown) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\r\n");
}

export default function ReportsPage() {
  const { t } = useTranslation();
  const types = useQuery({ queryKey: ["record-types"], queryFn: () => api<RecordType[]>("/records") });
  const [table, setTable] = useState("blast");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const page = useQuery({
    queryKey: ["records", table, q, offset],
    queryFn: () => api<Page>(`/records/${table}`, { q, offset, limit: PAGE }),
    placeholderData: keepPreviousData,
  });
  const cols = types.data?.find((x) => x.name === table)?.columns.filter((c) => c !== "created_at" && c !== "updated_at") ?? [];

  const exportCsv = () => {
    if (!page.data) return;
    const blob = new Blob(["﻿" + toCsv(page.data.items, cols)], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${table}_${offset + 1}-${offset + page.data.items.length}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div>
      <PageHeader title={t("reports.title")} subtitle={t("reports.subtitle")} />
      <div className="mb-4"><ReportGenerator /></div>
      <h2 className="text-[13px] font-semibold uppercase tracking-wide mb-2">{t("reports.database")}</h2>
      <div className="grid grid-cols-1 lg:grid-cols-[15rem_1fr] gap-4">
        <Card title={t("reports.tables")} bodyClass="p-0">
          {types.isLoading && <Loading />}
          <ul className="max-h-[70vh] overflow-y-auto scroll-thin py-1">
            {types.data?.map((x) => (
              <li key={x.name}>
                <button
                  onClick={() => { setTable(x.name); setOffset(0); setQ(""); }}
                  className={clsx("w-full flex justify-between px-4 py-1.5 text-[12.5px] font-mono", x.name === table ? "bg-accent-soft text-fg" : "text-fg-2 hover:bg-ink-750")}
                >
                  <span className="truncate">{x.name}</span>
                  <span className="tnum text-fg-3">{x.count}</span>
                </button>
              </li>
            ))}
          </ul>
        </Card>
        <Card
          title={<span className="font-mono normal-case">{table}</span>}
          subtitle={page.data ? `${page.data.total} ${t("common.records")}` : undefined}
          actions={
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-1.5 rounded border border-line bg-ink-900 px-2 py-1">
                <Search size={14} className="text-fg-3" />
                <input value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} placeholder={t("common.search")}
                  className="bg-transparent text-sm outline-none w-40" aria-label={t("common.search")} />
              </label>
              <button onClick={exportCsv} className="flex items-center gap-1.5 rounded border border-line px-2 py-1 text-sm text-fg-2 hover:text-fg hover:border-accent">
                <Download size={14} /> {t("reports.export")}
              </button>
            </div>
          }
          bodyClass="p-0"
        >
          {page.error && <ErrorState error={page.error} />}
          <div className="overflow-auto max-h-[64vh] scroll-thin">
            <table className="text-[12px] w-max min-w-full">
              <thead className="sticky top-0 bg-ink-750 text-fg-3">
                <tr>{cols.map((c) => <th key={c} className="text-left font-medium px-3 py-1.5 whitespace-nowrap">{c}</th>)}</tr>
              </thead>
              <tbody className="tnum">
                {page.data?.items.map((r) => (
                  <tr key={String(r.id)} className="border-t border-line-soft hover:bg-ink-750">
                    {cols.map((c) => (
                      <td key={c} className="px-3 py-1 whitespace-nowrap max-w-[22rem] truncate" title={r[c] == null ? "" : String(r[c])}>
                        {r[c] === null || r[c] === undefined ? <span className="text-fg-3">—</span> : typeof r[c] === "boolean" ? (r[c] ? "✓" : "✗") : String(r[c])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {page.data && (
            <div className="flex items-center justify-between px-4 py-2 border-t border-line-soft text-xs text-fg-3">
              <span className="tnum">
                {page.data.total ? offset + 1 : 0}–{offset + page.data.items.length} {t("common.of")} {page.data.total}
              </span>
              <div className="flex gap-2">
                <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))} className="px-2 py-1 rounded border border-line disabled:opacity-40">
                  {t("common.previous")}
                </button>
                <button disabled={offset + PAGE >= page.data.total} onClick={() => setOffset(offset + PAGE)} className="px-2 py-1 rounded border border-line disabled:opacity-40">
                  {t("common.next")}
                </button>
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
