import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useCan } from "../../auth/context";
import SystemCard from "./SystemCard";
import { Card, ErrorState, Loading, PageHeader, Pill } from "../../components/ui";
import { api, send } from "../../lib/api";
import { Button, Field, FormError, Input, Modal, Select } from "../../components/ui/forms";
import { fmtNum, label } from "../../lib/format";
import { useToday } from "../../lib/dates";
import { TemplatesCardBody } from "../operations/forms";

interface Limit { id: number; parameter: string; scope: string; min_value: number | null; max_value: number | null; unit: string; source_document: string; effective_from: string; owner: string; is_demo_placeholder: boolean }
interface Target { id: number; kpi_key: string; target: number; direction: string; is_demo_placeholder: boolean }

function LimitModal({ l, onClose }: { l: Limit; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const today = useToday();
  const [f, setF] = useState({ min_value: l.min_value === null ? "" : String(l.min_value), max_value: l.max_value === null ? "" : String(l.max_value), source_document: "", owner: "", effective_from: today });
  const mut = useMutation({
    mutationFn: () => send("PUT", `/settings/limits/${l.id}`, { ...f, min_value: f.min_value === "" ? null : Number(f.min_value), max_value: f.max_value === "" ? null : Number(f.max_value) }),
    onSuccess: () => { qc.invalidateQueries(); onClose(); },
  });
  return (
    <Modal title={`${label(l.parameter)} · ${l.scope} (${l.unit})`} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button><Button perm="config.limits" onClick={() => mut.mutate()}>{t("common.save")}</Button></>}>
      <div className="space-y-3">
        <p className="text-[12.5px] text-fg-3">{t("settings.limitHelp")}</p>
        <div className="grid grid-cols-3 gap-3">
          <Field label={t("settings.min")}><Input type="number" step="any" value={f.min_value} onChange={(e) => setF({ ...f, min_value: e.target.value })} /></Field>
          <Field label={t("settings.max")}><Input type="number" step="any" value={f.max_value} onChange={(e) => setF({ ...f, max_value: e.target.value })} /></Field>
          <Field label={t("settings.effective")}><Input type="date" value={f.effective_from} onChange={(e) => setF({ ...f, effective_from: e.target.value })} /></Field>
        </div>
        <Field label={t("settings.source")}><Input value={f.source_document} onChange={(e) => setF({ ...f, source_document: e.target.value })} placeholder="e.g. Product specification PS-E100 rev C" /></Field>
        <Field label={t("settings.owner")}><Input value={f.owner} onChange={(e) => setF({ ...f, owner: e.target.value })} /></Field>
        <FormError error={mut.error} />
      </div>
    </Modal>
  );
}

function NewLimitModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const today = useToday();
  const params = useQuery({ queryKey: ["md", "limit-params"], queryFn: () => api<{ parameter: string; unit: string }[]>("/masterdata/reference-limits/parameters") });
  const [f, setF] = useState({ parameter: "", scope: "*", min_value: "", max_value: "", source_document: "", owner: "", effective_from: today });
  const unit = params.data?.find((p) => p.parameter === f.parameter)?.unit;
  const mut = useMutation({
    mutationFn: () => send("POST", "/masterdata/reference-limits/new", { ...f, min_value: f.min_value === "" ? null : Number(f.min_value), max_value: f.max_value === "" ? null : Number(f.max_value) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["limits"] }); qc.invalidateQueries({ queryKey: ["md"] }); onClose(); },
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <Modal title={t("settings.newLimit")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button perm="config.limits" onClick={() => mut.mutate()} disabled={!f.parameter || (f.min_value === "" && f.max_value === "") || f.source_document.length < 3 || f.owner.length < 3 || mut.isPending}>{t("common.save")}</Button></>}>
      <div className="grid grid-cols-2 gap-3">
        <Field label={t("settings.parameter")}><Select value={f.parameter} onChange={set("parameter")}><option value="">{t("common.choose")}</option>{params.data?.map((p) => <option key={p.parameter} value={p.parameter}>{label(p.parameter)} ({p.unit})</option>)}</Select></Field>
        <Field label={t("settings.scope")} hint={t("settings.scopeHint")}><Input value={f.scope} onChange={set("scope")} /></Field>
        <Field label={`${t("settings.min")}${unit ? ` (${unit})` : ""}`}><Input type="number" step="any" value={f.min_value} onChange={set("min_value")} /></Field>
        <Field label={`${t("settings.max")}${unit ? ` (${unit})` : ""}`}><Input type="number" step="any" value={f.max_value} onChange={set("max_value")} /></Field>
        <Field label={t("settings.source")} className="col-span-2" hint={t("settings.sourceHint")}><Input value={f.source_document} onChange={set("source_document")} /></Field>
        <Field label={t("settings.owner")}><Input value={f.owner} onChange={set("owner")} /></Field>
        <Field label={t("settings.effective")}><Input type="date" value={f.effective_from} onChange={set("effective_from")} /></Field>
      </div>
      <div className="mt-3"><FormError error={mut.error} /></div>
    </Modal>
  );
}

export default function SettingsPage() {
  const { t } = useTranslation();
  const can = useCan();
  const limits = useQuery({ queryKey: ["limits"], queryFn: () => api<{ items: Limit[] }>("/records/reference_limit", { limit: 500 }) });
  const [edit, setEdit] = useState<Limit | null>(null);
  const [creating, setCreating] = useState(false);
  const targets = useQuery({ queryKey: ["targets"], queryFn: () => api<{ items: Target[] }>("/records/kpi_target", { limit: 500 }) });

  return (
    <div className="space-y-4 max-w-6xl">
      <PageHeader title={t("settings.title")} subtitle={t("settings.subtitle")} />
      {limits.data?.items.some((l) => l.is_demo_placeholder) && <div className="rounded-lg border border-warning/40 bg-warning/10 px-4 py-2.5 text-sm text-warning">{t("settings.placeholderWarn")}</div>}

      <Card title={t("settings.limits")} bodyClass="p-0 overflow-x-auto"
        actions={<Button perm="config.limits" variant="ghost" className="text-xs py-1" onClick={() => setCreating(true)}><Plus size={13} />{t("settings.newLimit")}</Button>}>
        {limits.isLoading && <Loading />}
        {limits.error && <ErrorState error={limits.error} />}
        <table className="w-full text-sm">
          <thead className="text-[11px] uppercase text-fg-3">
            <tr className="border-b border-line-soft">
              {["parameter", "scope", "min", "max", "unit", "source", ""].map((h) => (
                <th key={h} className={`px-3 py-2 font-medium ${h === "min" || h === "max" ? "text-right" : "text-left"}`}>{h ? t(`settings.${h}`) : ""}</th>
              ))}
            </tr>
          </thead>
          <tbody className="tnum">
            {limits.data?.items.map((l) => (
              <tr key={l.id} className="border-b border-line-soft last:border-0">
                <td className="px-3 py-1.5">{label(l.parameter)}</td>
                <td className="px-3 py-1.5 font-mono text-[12.5px]">{l.scope}</td>
                <td className="px-3 py-1.5 text-right">{fmtNum(l.min_value, 2)}</td>
                <td className="px-3 py-1.5 text-right">{fmtNum(l.max_value, 2)}</td>
                <td className="px-3 py-1.5">{l.unit}</td>
                <td className="px-3 py-1.5 text-[11.5px] text-fg-3 max-w-md">
                  {l.is_demo_placeholder && <Pill tone="warning" className="mr-2">DEMO</Pill>}
                  {l.source_document}
                </td>
                <td className="px-3 py-1.5">{can("config.limits") && <button onClick={() => setEdit(l)} className="text-fg-3 hover:text-accent" aria-label="edit"><Pencil size={14} /></button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card title={t("settings.targets")} bodyClass="p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-[11px] uppercase text-fg-3">
            <tr className="border-b border-line-soft">
              <th className="text-left px-3 py-2 font-medium">{t("settings.kpi")}</th>
              <th className="text-right px-3 py-2 font-medium">{t("common.target")}</th>
              <th className="text-left px-3 py-2 font-medium">{t("settings.direction")}</th>
              <th className="text-left px-3 py-2 font-medium" />
            </tr>
          </thead>
          <tbody className="tnum">
            {targets.data?.items.map((k) => (
              <tr key={k.id} className="border-b border-line-soft last:border-0">
                <td className="px-3 py-1.5">{t(`kpiNames.${k.kpi_key}`)}</td>
                <td className="px-3 py-1.5 text-right">{fmtNum(k.target)}{k.kpi_key.endsWith("_h") ? " h" : " %"}</td>
                <td className="px-3 py-1.5 text-fg-2">{k.direction === "HIGHER" ? t("settings.higher") : t("settings.lower")}</td>
                <td className="px-3 py-1.5">{k.is_demo_placeholder && <Pill tone="warning">DEMO</Pill>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card title={t("ops.templates")}><TemplatesCardBody /></Card>
      {can("system.backup") && <SystemCard />}
      {edit && <LimitModal l={edit} onClose={() => setEdit(null)} />}
      {creating && <NewLimitModal onClose={() => setCreating(false)} />}
    </div>
  );
}
