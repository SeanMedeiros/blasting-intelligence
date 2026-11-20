import i18n from "../i18n";

export function fmtNum(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return new Intl.NumberFormat(i18n.language === "fr" ? "fr-CA" : "en-CA", {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  }).format(v);
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? iso + "T12:00:00" : iso);
  return new Intl.DateTimeFormat(i18n.language === "fr" ? "fr-CA" : "en-CA", { month: "short", day: "numeric" }).format(d);
}

export function fmtDateLong(iso: string): string {
  const d = new Date(iso + "T12:00:00");
  return new Intl.DateTimeFormat(i18n.language === "fr" ? "fr-CA" : "en-CA", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(d);
}

/** Converts CONSTANT_CASE codes to a translated label, falling back to Title Case. */
export function label(code: string | null | undefined): string {
  if (!code) return "—";
  const key = `codes.${code}`;
  if (i18n.exists(key)) return i18n.t(key);
  return code
    .toLowerCase()
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
