import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DatabaseBackup } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Card, ErrorState, Loading, Pill } from "../../components/ui";
import { Button, FormError } from "../../components/ui/forms";
import { api, send } from "../../lib/api";

interface BackupInfo { file: string; size_bytes: number; created_at: string | null; reason: string | null; dialect: string | null; schema_revision: string | null; readable: boolean }
interface Status {
  app_version: string;
  database: { type: string; location: string };
  schema: { revision: string | null; head: string };
  backups: { directory: string; keep: number; daily_at: string | null; count: number; latest: BackupInfo | null };
  server: {
    address: string; listen: string; network: boolean; https: boolean; behind_proxy: boolean; cookie_secure: boolean;
    http_redirect_port: number | null; host_check: string[] | null; unencrypted_network: boolean;
    certificate: { subject?: string; names?: string[]; expires?: string; days_left?: number; expiring_soon?: boolean; error?: string } | null;
  };
}

const mb = (b: number) => `${(b / 1e6).toFixed(1)} MB`;
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "—");

/** Database status and backups — administrators only (permission system.backup). */
export default function SystemCard() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["system", "status"], queryFn: () => api<Status>("/system/status") });
  const list = useQuery({ queryKey: ["system", "backups"], queryFn: () => api<BackupInfo[]>("/system/backups") });
  const now = useMutation({
    mutationFn: () => send<BackupInfo>("POST", "/system/backups"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["system"] }),
  });
  const s = status.data;
  return (
    <Card title={t("system.title")} subtitle={t("system.subtitle")}
      actions={<Button perm="system.backup" onClick={() => now.mutate()} disabled={now.isPending}><DatabaseBackup size={14} />{now.isPending ? t("system.running") : t("system.backupNow")}</Button>}>
      {status.isPending ? <Loading /> : status.isError ? <ErrorState error={status.error} /> : s && (
        <div className="space-y-4">
          <dl className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 text-sm">
            <div><dt className="text-xs text-fg-3">{t("system.database")}</dt><dd className="font-medium">{s.database.type === "postgresql" ? "PostgreSQL" : "SQLite"}</dd>
              <dd className="text-[11px] text-fg-3 font-mono break-all">{s.database.location}</dd></div>
            <div><dt className="text-xs text-fg-3">{t("system.schema")}</dt>
              <dd>{s.schema.revision === s.schema.head ? <Pill tone="good">{t("system.upToDate")} · {s.schema.revision}</Pill> : <Pill tone="warning">{s.schema.revision ?? "—"} → {s.schema.head}</Pill>}</dd></div>
            <div><dt className="text-xs text-fg-3">{t("system.schedule")}</dt>
              <dd>{s.backups.daily_at ? t("system.dailyAt", { time: s.backups.daily_at }) : t("system.noSchedule")}</dd>
              <dd className="text-[11px] text-fg-3">{t("system.keep", { n: s.backups.keep })}</dd></div>
            <div><dt className="text-xs text-fg-3">{t("system.latest")}</dt>
              <dd>{s.backups.latest ? when(s.backups.latest.created_at) : <Pill tone="warning">{t("system.none")}</Pill>}</dd>
              <dd className="text-[11px] text-fg-3 font-mono break-all">{s.backups.directory}</dd></div>
          </dl>
          <ServerAccess s={s.server} />
          <FormError error={now.error} />
          <div className="max-h-64 overflow-y-auto scroll-thin border border-line-soft rounded">
            <table className="w-full text-[12.5px]">
              <thead className="text-[11px] uppercase text-fg-3 sticky top-0 bg-ink-800">
                <tr className="border-b border-line-soft">
                  <th className="text-left px-3 py-1.5 font-medium">{t("system.file")}</th>
                  <th className="text-left px-3 py-1.5 font-medium">{t("system.reason")}</th>
                  <th className="text-left px-3 py-1.5 font-medium">{t("system.created")}</th>
                  <th className="text-right px-3 py-1.5 font-medium">{t("system.size")}</th>
                </tr>
              </thead>
              <tbody className="tnum">
                {list.data?.length === 0 && <tr><td colSpan={4} className="px-3 py-2 text-fg-3">{t("system.none")}</td></tr>}
                {list.data?.map((b) => (
                  <tr key={b.file} className="border-b border-line-soft last:border-0">
                    <td className="px-3 py-1 font-mono break-all">{b.file}</td>
                    <td className="px-3 py-1">{b.readable ? b.reason : <Pill tone="critical">{t("system.unreadable")}</Pill>}</td>
                    <td className="px-3 py-1 whitespace-nowrap">{when(b.created_at)}</td>
                    <td className="px-3 py-1 text-right">{mb(b.size_bytes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[11.5px] text-fg-3">{t("system.restoreHint")}</p>
        </div>
      )}
    </Card>
  );
}

function ServerAccess({ s }: { s: Status["server"] }) {
  const { t } = useTranslation();
  const c = s.certificate;
  const enc = s.https ? <Pill tone="good">{t("system.httpsOn")}</Pill>
    : s.behind_proxy ? <Pill tone="good">{t("system.httpsProxy")}</Pill>
    : s.unencrypted_network ? <Pill tone="critical">{t("system.httpsOffNetwork")}</Pill>
    : <Pill tone="neutral">{t("system.httpsOffLocal")}</Pill>;
  return (
    <dl className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 text-sm border-t border-line-soft pt-3" data-testid="server-access">
      <div><dt className="text-xs text-fg-3">{t("system.address")}</dt><dd className="font-mono text-[12.5px] break-all">{s.address}</dd>
        <dd className="text-[11px] text-fg-3">{t("system.listen", { at: s.listen })}{s.http_redirect_port ? ` · ${t("system.redirect", { port: s.http_redirect_port })}` : ""}</dd></div>
      <div><dt className="text-xs text-fg-3">{t("system.encryption")}</dt><dd>{enc}</dd>
        <dd className="text-[11px] text-fg-3">{s.cookie_secure ? t("system.cookieSecure") : t("system.cookiePlain")}</dd></div>
      <div><dt className="text-xs text-fg-3">{t("system.certificate")}</dt>
        <dd>{!c ? "—" : c.error ? <Pill tone="critical">{c.error}</Pill>
          : <Pill tone={(c.days_left ?? 0) < 0 ? "critical" : c.expiring_soon ? "warning" : "good"}>{t("system.certExpires", { date: c.expires?.slice(0, 10), n: c.days_left })}</Pill>}</dd>
        {c?.names && <dd className="text-[11px] text-fg-3 font-mono break-words">{c.names.join(", ")}</dd>}</div>
      <div><dt className="text-xs text-fg-3">{t("system.hostCheck")}</dt>
        <dd className="text-[11px] text-fg-3 font-mono break-words">{s.host_check ? s.host_check.join(", ") : t("system.hostCheckOff")}</dd></div>
    </dl>
  );
}
