import clsx from "clsx";
import { CalendarDays, ChevronDown, FlaskConical, KeyRound, LogOut, Menu, UserRound, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { setLanguage } from "../i18n";
import { useAuth } from "../auth/context";
import { ChangePasswordForm } from "../auth/ChangePasswordPage";
import { Modal } from "../components/ui/forms";
import { useMeta } from "../lib/dates";
import { fmtDateLong } from "../lib/format";
import { NAV } from "./nav";

function Logo() {
  return (
    <div className="flex items-center gap-2.5 px-4 h-14 border-b border-line">
      <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden>
        <rect width="32" height="32" rx="6" fill="#131c2b" stroke="#22304a" />
        <path d="M6 23 L13 11 L18 18 L21 14 L26 23 Z" fill="none" stroke="#e8742c" strokeWidth="2.4" strokeLinejoin="round" />
      </svg>
      <div className="leading-tight">
        <div className="text-[13px] font-bold tracking-wider text-fg">BLASTING</div>
        <div className="text-[10px] tracking-[0.2em] text-accent font-semibold">INTELLIGENCE</div>
      </div>
    </div>
  );
}

function UserMenu() {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [pwd, setPwd] = useState(false);
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 text-xs text-fg-2 hover:text-fg rounded border border-line px-2 py-1"
        aria-haspopup="menu"
        aria-expanded={open}
        data-testid="user-menu"
      >
        <UserRound size={14} className="text-fg-3" aria-hidden />
        <span className="max-w-[10rem] truncate text-fg">{user.full_name}</span>
        <span className="hidden md:inline text-fg-3">· {t(`roles.${user.role}`)}</span>
        <ChevronDown size={12} aria-hidden />
      </button>
      {open && (
        <>
          <button className="fixed inset-0 z-30 cursor-default" aria-hidden tabIndex={-1} onClick={() => setOpen(false)} />
          <div role="menu" className="absolute right-0 mt-1 z-40 w-56 rounded border border-line bg-ink-800 shadow-xl py-1 text-sm">
            <div className="px-3 py-2 border-b border-line-soft">
              <div className="text-fg font-medium truncate">{user.full_name}</div>
              <div className="text-[11px] text-fg-3 font-mono">{user.username} · {t(`roles.${user.role}`)}</div>
            </div>
            <button role="menuitem" className="w-full text-left px-3 py-2 hover:bg-ink-750 flex items-center gap-2" onClick={() => { setPwd(true); setOpen(false); }}>
              <KeyRound size={14} aria-hidden />{t("auth.changePassword")}
            </button>
            <button role="menuitem" className="w-full text-left px-3 py-2 hover:bg-ink-750 flex items-center gap-2" onClick={() => logout()}>
              <LogOut size={14} aria-hidden />{t("auth.signOut")}
            </button>
          </div>
        </>
      )}
      {pwd && (
        <Modal title={t("auth.changePassword")} onClose={() => setPwd(false)}>
          <ChangePasswordForm user={user} onDone={() => setPwd(false)} onCancel={() => setPwd(false)} />
        </Modal>
      )}
    </div>
  );
}

export default function Layout() {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  const meta = useMeta();
  // a new screen opens at its top (the scrolling area is shared by every page)
  const mainRef = useRef<HTMLElement>(null);
  const { pathname } = useLocation();
  useEffect(() => { mainRef.current?.scrollTo({ top: 0 }); }, [pathname]);
  const { can } = useAuth();

  const sidebar = (
    <nav className="flex flex-col h-full bg-ink-900 border-r border-line w-60">
      <Logo />
      <ul className="flex-1 overflow-y-auto scroll-thin py-2">
        {NAV.filter((x) => !x.perm || can(x.perm)).map(({ key, path, icon: Icon, n }) => (
          <li key={key}>
            <NavLink
              to={path}
              end={path === "/"}
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                clsx(
                  "flex items-center gap-3 px-4 py-2 text-[13px] border-l-2 transition-colors",
                  isActive ? "border-accent bg-accent-soft text-fg font-medium" : "border-transparent text-fg-2 hover:text-fg hover:bg-ink-800",
                )
              }
            >
              <span className="text-[10px] w-4 text-fg-3 tnum">{String(n).padStart(2, "0")}</span>
              <Icon size={16} strokeWidth={1.8} aria-hidden />
              <span className="truncate">{t(`nav.${key}`)}</span>
            </NavLink>
          </li>
        ))}
      </ul>
      <div className="p-3 border-t border-line text-[10.5px] leading-snug text-fg-3">{t("app.humanControl")}</div>
    </nav>
  );

  return (
    <div className="flex h-screen overflow-hidden">
      <div className="hidden lg:block shrink-0">{sidebar}</div>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden flex">
          {sidebar}
          <button className="flex-1 bg-black/50" aria-label={t("common.close")} onClick={() => setOpen(false)} />
        </div>
      )}
      <div className="flex-1 flex flex-col min-w-0">
        {meta.data?.mode === "demo" && (
          <div className="bg-accent/90 text-ink-950 text-[11px] font-bold tracking-wider text-center py-1 flex items-center justify-center gap-2" role="note">
            <FlaskConical size={12} aria-hidden /> {t("app.disclaimer")}
          </div>
        )}
        <header className="h-12 shrink-0 flex items-center gap-3 px-4 border-b border-line bg-ink-900/60">
          <button className="lg:hidden text-fg-2" onClick={() => setOpen(true)} aria-label="Menu">
            {open ? <X size={20} /> : <Menu size={20} />}
          </button>
          <div className="text-sm text-fg-2 truncate">
            <span className="text-fg font-medium">{meta.data?.site_configured ? meta.data.site : t("app.noSite")}</span>
            <span className="hidden 2xl:inline text-fg-3"> · {t("app.tagline")}</span>
          </div>
          <div className="ml-auto flex items-center gap-4">
            <UserMenu />
            {meta.data && (
              <div className="hidden sm:flex items-center gap-1.5 text-xs text-fg-2" title={meta.data.mode === "demo" ? t("app.demoClock") : meta.data.timezone}>
                <CalendarDays size={14} className="text-accent" aria-hidden />
                {meta.data.mode === "demo" && <span className="text-fg-3 hidden 2xl:inline">{t("app.demoClock")}:</span>}
                <span className="text-fg tnum" data-testid="today">{fmtDateLong(meta.data.today)}</span>
              </div>
            )}
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
        </header>
        <div className="flex-1 flex min-h-0">
          <main ref={mainRef} className="flex-1 overflow-y-auto scroll-thin p-4 lg:p-6 min-w-0">
            {/* pages initialise their default dates from the operational date (site time zone / demo date): wait for it */}
            {meta.data || meta.isError ? <Outlet /> : null}
          </main>
        </div>
      </div>
    </div>
  );
}
