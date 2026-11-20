import { useQuery } from "@tanstack/react-query";
import { api, type Meta } from "./api";

/** Site metadata (mode, operational date, site name). Refreshed every 10 minutes so "today" rolls over at midnight. */
export function useMeta() {
  return useQuery({ queryKey: ["meta"], queryFn: () => api<Meta>("/meta"), staleTime: 10 * 60_000, refetchInterval: 10 * 60_000 });
}

function localIso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Operational date (ISO yyyy-mm-dd) from the server: the site's date in production, the fixed date in demo mode. */
export function useToday(): string {
  const meta = useMeta();
  return meta.data?.today ?? localIso(new Date());
}

export function addDays(iso: string, n: number): string {
  const d = new Date(iso + "T12:00:00");
  d.setDate(d.getDate() + n);
  return localIso(d);
}

/** Monday of the week containing `iso`. */
export function weekStart(iso: string): string {
  const d = new Date(iso + "T12:00:00");
  return addDays(iso, -((d.getDay() + 6) % 7));
}

export function monthOf(iso: string): string {
  return iso.slice(0, 7);
}

/** `n` months ending with the month of `iso`, oldest first (yyyy-mm). */
export function lastMonths(iso: string, n: number): string[] {
  const [y, m] = iso.split("-").map(Number);
  const out: string[] = [];
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(y, m - 1 - i, 1);
    out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
  }
  return out;
}

export function firstOfMonth(ym: string): string {
  return `${ym}-01`;
}

/** Local date-time for <input type="datetime-local"> on the operational date, current time of day. */
export function nowOn(iso: string): string {
  const t = new Date();
  return `${iso}T${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")}`;
}
