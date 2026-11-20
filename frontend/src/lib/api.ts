export class ApiError extends Error {
  /** `detail` keeps the server's structured error (e.g. { message, unmet } or { message, used_by }). */
  constructor(public status: number, message: string, public detail?: unknown) {
    super(message);
  }
}

import i18n from "../i18n";

/** Language of server texts (errors, KPI names, alerts, reports) — follows the UI language. */
export const lang = () => (i18n.language === "fr" ? "fr" : "en");

/** Adds `lang=` to a download link (PDF/CSV opened by the browser, which cannot send our headers). */
export function withLang(url: string): string {
  return url + (url.includes("?") ? "&" : "?") + `lang=${lang()}`;
}

/** Header that the server requires on every state-changing request made with the session cookie (CSRF guard). */
const CSRF = { "X-Requested-With": "blasting-intelligence" };

/** Fired on 401 so the app can show the sign-in screen. */
export const UNAUTHORIZED_EVENT = "bi:unauthorized";

async function fail(res: Response): Promise<never> {
  let msg: unknown = res.statusText;
  let raw: unknown;
  try {
    const j = await res.json();
    msg = j.detail ?? msg;
    raw = j.detail;
  } catch {
    /* non-JSON body */
  }
  if (res.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  if (msg && typeof msg === "object" && !Array.isArray(msg) && "message" in msg) {
    const o = msg as { message: string; unmet?: string[]; used_by?: Record<string, number> };
    msg = o.message + (o.unmet?.length ? ` — ${o.unmet.join("; ")}` : "")
      + (o.used_by ? ` (${Object.entries(o.used_by).map(([k, n]) => `${k}: ${n}`).join(", ")})` : "");
  }
  if (Array.isArray(msg)) msg = msg.map((e: { msg?: string }) => e.msg ?? "").join("; ");
  throw new ApiError(res.status, typeof msg === "string" ? msg : JSON.stringify(msg), raw);
}

export async function send<T>(method: "POST" | "PATCH" | "PUT" | "DELETE", path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    method,
    headers: { "Content-Type": "application/json", "X-Lang": lang(), ...CSRF },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) await fail(res);
  return res.json() as Promise<T>;
}

export async function upload<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`/api/v1${path}`, { method: "POST", headers: { ...CSRF, "X-Lang": lang() }, body: form });
  if (!res.ok) await fail(res);
  return res.json() as Promise<T>;
}

export async function binary(path: string, params?: Record<string, string | undefined>): Promise<ArrayBuffer> {
  const qs = params ? "?" + Object.entries(params).filter(([, v]) => v !== undefined).map(([k, v]) => `${k}=${encodeURIComponent(v!)}`).join("&") : "";
  const res = await fetch(`/api/v1${path}${qs}`, { headers: { "X-Lang": lang() } });
  if (!res.ok) await fail(res);
  return res.arrayBuffer();
}

export async function api<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
  const qs = params
    ? "?" +
      Object.entries(params)
        .filter(([, v]) => v !== undefined && v !== "")
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join("&")
    : "";
  const res = await fetch(`/api/v1${path}${qs}`, { headers: { "X-Lang": lang() } });
  if (!res.ok) await fail(res);
  return res.json() as Promise<T>;
}

// ---- shared types
export type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";

export interface Alert {
  rule: string;
  severity: Severity;
  title: string;
  detail: string;
  module: string;
  refs: string[];
}

export interface Kpi {
  key: string;
  name: string;
  unit: string;
  value: number | null;
  numerator: number;
  denominator: number;
  numerator_label: string;
  denominator_label: string;
  formula: string;
  target: number | null;
  direction: "HIGHER" | "LOWER" | null;
  target_is_demo: boolean;
  status: "ON_TARGET" | "NEAR_TARGET" | "OFF_TARGET" | "NO_DATA";
  period: { start: string; end: string };
}

export interface Meta {
  app: string;
  version: string;
  mode: "production" | "demo";
  disclaimer: string | null;
  today: string;
  timezone: string;
  site: string;
  site_configured: boolean;
  password_min_length: number;
}

export type Role = "ADMIN" | "ENGINEER" | "TECHNICIAN" | "QSSE" | "VIEWER";

export interface Me {
  id: number;
  username: string;
  full_name: string;
  email: string | null;
  role: Role;
  must_change_password: boolean;
  permissions: string[];
  personnel_id: number | null;
}

export interface Dashboard {
  today: string;
  activities: { id: number; work_order: string; activity: string; status: string; planned_date: string; responsible: string | null; resources: string | null }[];
  blast_status_counts: Record<string, number>;
  pending_blasts: {
    code: string;
    status: string;
    planned_date: string;
    bench: string;
    approved_plan_ref: string;
    authorization_ref: string | null;
    verification: { holes: number; measured: number; out_of_tolerance: number };
  }[];
  deliveries: { code: string; product: string; area: string; planned_date: string; actual_date: string | null; planned_qty: number; delivered_qty: number | null; unit: string; status: string }[];
  equipment: { code: string; name: string; type: string; status: string; availability_30d: number }[];
  surveys: { last_30d: Record<string, number>; missing_post_blast: string[] };
  laboratory: { tests: number; by_result: Record<string, number>; by_type: Record<string, number>; open_nonconformances: number; quarantined_batches: string[] };
  vibration: { station: string; name: string; events: number; valid: number; max_ppv: number | null; limit: number | null; exceedances: number }[];
  safety: { open_observations: number; open_by_risk: Record<string, number>; open_capa: number; overdue_capa: number; near_misses_30d: number };
  kpis: Kpi[];
  kpi_trend: { labels: string[]; series: Record<string, (number | null)[]> };
  alerts: Alert[];
}
