import clsx from "clsx";
import { AlertOctagon, AlertTriangle, CheckCircle2, Circle, Info, Loader2, MinusCircle, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { label } from "../../lib/format";

export function Card({ title, subtitle, actions, children, className, bodyClass }: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string;
}) {
  return (
    <section className={clsx("rounded-lg border border-line bg-ink-800 flex flex-col min-w-0", className)}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 px-4 pt-3 pb-2 border-b border-line-soft">
          <div className="min-w-0">
            {title && <h2 className="text-[13px] font-semibold tracking-wide text-fg uppercase">{title}</h2>}
            {subtitle && <p className="text-xs text-fg-3 mt-0.5">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      <div className={clsx("p-4 flex-1 min-h-0", bodyClass)}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: string; right?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 mb-4">
      <div>
        <h1 className="text-xl font-semibold text-fg">{title}</h1>
        {subtitle && <p className="text-sm text-fg-3 mt-0.5">{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

type Tone = "good" | "warning" | "serious" | "critical" | "info" | "neutral" | "accent";

const toneClass: Record<Tone, string> = {
  good: "text-good border-good/40 bg-good/10",
  warning: "text-warning border-warning/40 bg-warning/10",
  serious: "text-serious border-serious/40 bg-serious/10",
  critical: "text-critical border-critical/50 bg-critical/10",
  info: "text-series-1 border-series-1/40 bg-series-1/10",
  accent: "text-accent border-accent/40 bg-accent/10",
  neutral: "text-fg-2 border-line bg-ink-750",
};

const toneIcon: Record<Tone, typeof Info> = {
  good: CheckCircle2, warning: AlertTriangle, serious: AlertTriangle, critical: AlertOctagon,
  info: Info, accent: Circle, neutral: MinusCircle,
};

/** Status pill: icon + label, never colour alone. */
export function Pill({ tone = "neutral", children, icon = true, className }: { tone?: Tone; children: ReactNode; icon?: boolean; className?: string }) {
  const Icon = toneIcon[tone];
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap", toneClass[tone], className)}>
      {icon && <Icon size={12} strokeWidth={2.2} aria-hidden />}
      {children}
    </span>
  );
}

const STATUS_TONE: Record<string, Tone> = {
  ON_TARGET: "good", NEAR_TARGET: "warning", OFF_TARGET: "critical", NO_DATA: "neutral",
  CRITICAL: "critical", HIGH: "serious", MEDIUM: "warning", LOW: "info",
  PLANNED: "neutral", IN_PREPARATION: "info", UNDER_INSPECTION: "warning", AUTHORIZED: "accent",
  IN_PROGRESS: "info", AWAITING_VERIFICATION: "warning", COMPLETED: "good", CLOSED: "neutral",
  DONE: "good", DELAYED: "critical", SCHEDULED: "neutral", DELIVERED: "good", LATE: "serious", PARTIAL: "warning",
  AVAILABLE: "good", DOWN: "critical", MAINTENANCE: "warning",
  ACCEPTED: "good", PENDING: "warning", REJECTED: "critical",
  PASS: "good", FAIL: "critical", NOT_EVALUATED: "neutral",
  OPEN: "warning", CLOSED_OK: "good",
};

export function StatusPill({ status, text }: { status: string; text?: string }) {
  const { t } = useTranslation();
  const known = t(`status.${status}`, { defaultValue: "" });
  return <Pill tone={STATUS_TONE[status] ?? "neutral"}>{text ?? (known || label(status))}</Pill>;
}

export function Progress({ value, max, tone = "info" }: { value: number; max: number; tone?: Tone }) {
  const pct = max ? Math.min(100, (100 * value) / max) : 0;
  const bar = { good: "bg-good", warning: "bg-warning", serious: "bg-serious", critical: "bg-critical", info: "bg-series-1", accent: "bg-accent", neutral: "bg-fg-3" }[tone];
  return (
    <div className="h-1.5 w-full rounded-full bg-ink-700 overflow-hidden" role="meter" aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
      <div className={clsx("h-full rounded-full", bar)} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Loading() {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-2 text-fg-3 text-sm p-6">
      <Loader2 className="animate-spin" size={16} /> {t("common.loading")}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="rounded-lg border border-critical/40 bg-critical/10 p-4 text-sm flex items-start gap-3">
      <XCircle className="text-critical shrink-0" size={18} />
      <div>
        <div className="font-medium text-fg">{t("common.error")}</div>
        <div className="text-fg-3 mt-1">{error instanceof Error ? error.message : String(error)}</div>
        {onRetry && (
          <button onClick={onRetry} className="mt-2 text-accent hover:underline">
            {t("common.retry")}
          </button>
        )}
      </div>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="text-sm text-fg-3 py-4 text-center">{children}</div>;
}
