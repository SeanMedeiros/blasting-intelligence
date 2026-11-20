import clsx from "clsx";
import { Lock, X } from "lucide-react";
import { useEffect, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { useTranslation } from "react-i18next";
import { useCan } from "../../auth/context";

export function Modal({ title, children, onClose, footer, wide }: { title: ReactNode; children: ReactNode; onClose: () => void; footer?: ReactNode; wide?: boolean }) {
  const { t } = useTranslation();
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onMouseDown={onClose} role="dialog" aria-modal="true">
      <div className={clsx("w-full rounded-lg border border-line bg-ink-800 shadow-2xl max-h-[92vh] flex flex-col", wide ? "max-w-3xl" : "max-w-lg")}
        onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-3 border-b border-line">
          <h3 className="text-base font-semibold">{title}</h3>
          <button onClick={onClose} className="text-fg-3 hover:text-fg" aria-label={t("common.close")}><X size={18} /></button>
        </div>
        <div className="p-5 overflow-y-auto scroll-thin text-sm">{children}</div>
        {footer && <div className="px-5 py-3 border-t border-line flex justify-end gap-2">{footer}</div>}
      </div>
    </div>
  );
}

export function Field({ label, hint, children, className }: { label: string; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={clsx("block", className)}>
      <span className="block text-xs text-fg-3 mb-1">{label}</span>
      {children}
      {hint && <span className="block text-[11px] text-fg-3 mt-1">{hint}</span>}
    </label>
  );
}

const base = "w-full rounded border border-line bg-ink-900 px-2.5 py-1.5 text-sm text-fg outline-none focus:border-accent";

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={clsx(base, props.className)} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={clsx(base, props.className)} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea rows={3} {...props} className={clsx(base, props.className)} />;
}

/**
 * `perm`: permission required for the action. Without it the button is disabled with a lock icon
 * and a tooltip; the server enforces the same rule independently.
 */
export function Button({ variant = "primary", className, perm, children, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger"; perm?: string }) {
  const can = useCan();
  const { t } = useTranslation();
  const denied = perm !== undefined && !can(perm);
  return (
    <button
      {...p}
      disabled={p.disabled || denied}
      title={denied ? t("auth.noPermission") : p.title}
      data-perm={perm}
      className={clsx(
        "inline-flex items-center justify-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors",
        variant === "primary" && "bg-accent text-ink-950 hover:bg-accent/90",
        variant === "ghost" && "border border-line text-fg-2 hover:text-fg hover:border-accent",
        variant === "danger" && "bg-critical text-white hover:bg-critical/90",
        className,
      )}
    >
      {denied && <Lock size={12} aria-hidden />}
      {children}
    </button>
  );
}

export function FormError({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="rounded border border-critical/40 bg-critical/10 px-3 py-2 text-[13px] text-fg">{error instanceof Error ? error.message : String(error)}</div>;
}
