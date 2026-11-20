import clsx from "clsx";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { setLanguage } from "../i18n";

/** Centered card used by the sign-in and password screens. */
export default function AuthShell({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  const { t, i18n } = useTranslation();
  return (
    <div className="min-h-screen grid place-items-center bg-ink-950 p-4">
      <div className="w-full max-w-sm">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2.5">
            <svg width="32" height="32" viewBox="0 0 32 32" aria-hidden>
              <rect width="32" height="32" rx="6" fill="#131c2b" stroke="#22304a" />
              <path d="M6 23 L13 11 L18 18 L21 14 L26 23 Z" fill="none" stroke="#e8742c" strokeWidth="2.4" strokeLinejoin="round" />
            </svg>
            <div className="leading-tight">
              <div className="text-sm font-bold tracking-wider text-fg">BLASTING</div>
              <div className="text-[10px] tracking-[0.2em] text-accent font-semibold">INTELLIGENCE</div>
            </div>
          </div>
          <div className="flex rounded border border-line overflow-hidden text-xs" role="group" aria-label={t("settings.language")}>
            {(["en", "fr"] as const).map((l) => (
              <button
                key={l}
                onClick={() => setLanguage(l)}
                className={clsx("px-2 py-1 uppercase", i18n.language === l ? "bg-accent text-ink-950 font-semibold" : "text-fg-2 hover:bg-ink-800")}
                aria-pressed={i18n.language === l}
              >
                {l}
              </button>
            ))}
          </div>
        </div>
        <section className="rounded-lg border border-line bg-ink-800 p-6">
          <h1 className="text-lg font-semibold text-fg">{title}</h1>
          {subtitle && <p className="text-sm text-fg-3 mt-1">{subtitle}</p>}
          <div className="mt-5">{children}</div>
        </section>
        <p className="text-[11px] text-fg-3 mt-4 text-center">{t("app.humanControl")}</p>
      </div>
    </div>
  );
}
