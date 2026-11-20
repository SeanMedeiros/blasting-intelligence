import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Card } from "../../components/ui";
import { api } from "../../lib/api";

interface Status { complete: boolean; steps: { key: string; count: number; done: boolean }[] }

const LINK: Record<string, string> = {
  reference_limit: "/settings", kpi_target: "/kpi", app_user: "/users",
};

/** First-run checklist shown until every reference record a site needs exists. */
export default function SetupCard() {
  const { t } = useTranslation();
  const st = useQuery({ queryKey: ["md", "setup"], queryFn: () => api<Status>("/masterdata/setup/status") });
  if (!st.data || st.data.complete) return null;
  const done = st.data.steps.filter((s) => s.done).length;
  return (
    <Card title={t("setup.title")} subtitle={t("setup.subtitle", { done, total: st.data.steps.length })} className="border-accent/50">
      <ol className="grid sm:grid-cols-2 xl:grid-cols-4 gap-2" data-testid="setup-checklist">
        {st.data.steps.map((s, i) => (
          <li key={s.key}>
            <Link to={LINK[s.key] ?? `/masterdata?entity=${s.key}`}
              className="flex items-start gap-2 rounded border border-line-soft px-3 py-2 hover:border-accent text-sm">
              {s.done ? <CheckCircle2 size={16} className="text-good mt-0.5 shrink-0" aria-label={t("setup.done")} />
                : <Circle size={16} className="text-fg-3 mt-0.5 shrink-0" aria-label={t("setup.todo")} />}
              <span>
                <span className="text-fg-3 tnum mr-1">{i + 1}.</span>{t(`setup.step.${s.key}`)}
                <span className="block text-[11px] text-fg-3">{s.done ? t("setup.count", { n: s.count }) : t(`setup.hint.${s.key}`)}</span>
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </Card>
  );
}
