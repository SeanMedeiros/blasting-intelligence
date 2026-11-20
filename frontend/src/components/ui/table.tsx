import clsx from "clsx";
import { ArrowDown, ArrowUp } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

export interface Column<T> {
  key: string;
  header: ReactNode;
  render?: (row: T) => ReactNode;
  value?: (row: T) => string | number | null | undefined;
  align?: "left" | "right";
  className?: string;
}

/** Sortable, paginated table. Text filtering is done by the caller. */
export function DataTable<T>({ rows, columns, rowKey, onRowClick, selectedKey, pageSize = 25, empty, maxHeight = "32rem" }: {
  rows: T[]; columns: Column<T>[]; rowKey: (r: T) => string | number; onRowClick?: (r: T) => void; selectedKey?: string | number | null;
  pageSize?: number; empty?: ReactNode; maxHeight?: string;
}) {
  const { t } = useTranslation();
  const [sort, setSort] = useState<{ key: string; desc: boolean } | null>(null);
  const [page, setPage] = useState(0);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    const get = col?.value ?? ((r: T) => (r as Record<string, unknown>)[sort.key] as string | number);
    return [...rows].sort((a, b) => {
      const va = get(a), vb = get(b);
      if (va === vb) return 0;
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      return (va < vb ? -1 : 1) * (sort.desc ? -1 : 1);
    });
  }, [rows, sort, columns]);
  const pages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const p = Math.min(page, pages - 1);
  const shown = sorted.slice(p * pageSize, (p + 1) * pageSize);
  return (
    <div>
      <div className="overflow-auto scroll-thin" style={{ maxHeight }}>
        <table className="w-full text-[12.5px]">
          <thead className="sticky top-0 bg-ink-750 z-[1]">
            <tr>
              {columns.map((c) => (
                <th key={c.key} className={clsx("px-3 py-2 font-medium text-[11px] uppercase tracking-wide text-fg-3 whitespace-nowrap", c.align === "right" ? "text-right" : "text-left")}>
                  <button className="inline-flex items-center gap-1 hover:text-fg" onClick={() => setSort(sort?.key === c.key ? { key: c.key, desc: !sort.desc } : { key: c.key, desc: false })}>
                    {c.header}
                    {sort?.key === c.key && (sort.desc ? <ArrowDown size={11} /> : <ArrowUp size={11} />)}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="tnum">
            {shown.length === 0 && (
              <tr><td colSpan={columns.length} className="px-3 py-6 text-center text-fg-3">{empty ?? t("common.none")}</td></tr>
            )}
            {shown.map((r) => {
              const k = rowKey(r);
              return (
                <tr key={k} onClick={onRowClick ? () => onRowClick(r) : undefined}
                  className={clsx("border-t border-line-soft", onRowClick && "cursor-pointer hover:bg-ink-750", selectedKey === k && "bg-accent-soft")}>
                  {columns.map((c) => (
                    <td key={c.key} className={clsx("px-3 py-1.5 align-top", c.align === "right" && "text-right", c.className ?? "whitespace-nowrap")}>
                      {c.render ? c.render(r) : String((r as Record<string, unknown>)[c.key] ?? "—")}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="flex items-center justify-between px-3 py-2 border-t border-line-soft text-xs text-fg-3">
          <span className="tnum">{p * pageSize + 1}–{Math.min((p + 1) * pageSize, sorted.length)} {t("common.of")} {sorted.length}</span>
          <div className="flex gap-2">
            <button disabled={p === 0} onClick={() => setPage(p - 1)} className="px-2 py-1 rounded border border-line disabled:opacity-40">{t("common.previous")}</button>
            <button disabled={p >= pages - 1} onClick={() => setPage(p + 1)} className="px-2 py-1 rounded border border-line disabled:opacity-40">{t("common.next")}</button>
          </div>
        </div>
      )}
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { v: T; l: ReactNode; badge?: number }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="flex flex-wrap gap-1 border-b border-line mb-4" role="tablist">
      {tabs.map((tb) => (
        <button key={tb.v} role="tab" aria-selected={value === tb.v} onClick={() => onChange(tb.v)}
          className={clsx("px-3 py-2 text-sm -mb-px border-b-2", value === tb.v ? "border-accent text-fg font-medium" : "border-transparent text-fg-3 hover:text-fg")}>
          {tb.l}
          {tb.badge ? <span className="ml-1.5 rounded bg-critical/20 text-critical px-1.5 text-[11px] tnum">{tb.badge}</span> : null}
        </button>
      ))}
    </div>
  );
}

export function Stat({ label, value, sub, tone }: { label: ReactNode; value: ReactNode; sub?: ReactNode; tone?: "critical" | "warning" | "good" }) {
  return (
    <div className="rounded-lg border border-line bg-ink-800 p-3">
      <div className="text-[11px] text-fg-3">{label}</div>
      <div className={clsx("text-2xl font-semibold tnum", tone === "critical" && "text-critical", tone === "warning" && "text-warning", tone === "good" && "text-good")}>{value}</div>
      {sub && <div className="text-[11px] text-fg-3">{sub}</div>}
    </div>
  );
}
