import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { Card, ErrorState, Loading, PageHeader, Pill } from "../../components/ui";
import { Button, Field, FormError, Input, Modal, Select, Textarea } from "../../components/ui/forms";
import { DataTable, type Column } from "../../components/ui/table";
import { api, send } from "../../lib/api";
import { fmtDate, fmtNum, label } from "../../lib/format";
import { useOptions } from "../../lib/options";
import { AttachmentsPanel } from "../../components/Attachments";

export interface FieldDef {
  name: string; kind: "text" | "longtext" | "number" | "date" | "bool" | "choice" | "ref";
  required: boolean; max_len: number | null; choices: string[]; ref: string | null; min: number | null; max: number | null;
}
export interface EntityDef { key: string; group: string; label_field: string; can_edit: boolean; has_active: boolean; fields: FieldDef[] }
type Row = Record<string, unknown> & { id: number };

const GROUPS = ["site", "people", "equipment", "products"];
const ATTACHABLE = new Set(["calibration", "training_record"]);  // certificates

function RefSelect({ f, value, onChange, currentLabel }: { f: FieldDef; value: string; onChange: (v: string) => void; currentLabel?: string }) {
  const { t } = useTranslation();
  const opts = useOptions(f.ref!);
  const has = opts.data?.some((o) => String(o.id) === value);
  return (
    <Select value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{f.required ? t("common.choose") : "—"}</option>
      {value && !has && currentLabel && <option value={value}>{currentLabel} ({t("md.inactive")})</option>}
      {opts.data?.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
    </Select>
  );
}

function EditModal({ e, row, onClose }: { e: EntityDef; row: Row | null; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const init = Object.fromEntries(e.fields.map((f) => {
    const v = row?.[f.name];
    if (f.kind === "bool") return [f.name, row ? Boolean(v) : true];
    return [f.name, v === null || v === undefined ? "" : String(v)];
  }));
  const [vals, setVals] = useState<Record<string, string | boolean>>(init);
  const payload = () => Object.fromEntries(e.fields.map((f) => {
    const v = vals[f.name];
    if (f.kind === "bool") return [f.name, v];
    if (v === "") return [f.name, null];
    if (f.kind === "number" || f.kind === "ref") return [f.name, Number(v)];
    return [f.name, v];
  }));
  const mut = useMutation({
    mutationFn: () => (row ? send("PATCH", `/masterdata/${e.key}/${row.id}`, payload()) : send("POST", `/masterdata/${e.key}`, payload())),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["md"] }); qc.invalidateQueries({ queryKey: ["meta"] }); onClose(); },
  });
  const missing = e.fields.some((f) => f.required && f.kind !== "bool" && vals[f.name] === "");
  const set = (k: string, v: string | boolean) => setVals({ ...vals, [k]: v });
  return (
    <Modal wide title={`${row ? t("common.edit") : t("md.new")} — ${t(`md.entity.${e.key}`)}`} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button onClick={() => mut.mutate()} disabled={missing || mut.isPending || !e.can_edit}>{t("common.save")}</Button></>}>
      <div className="grid sm:grid-cols-2 gap-3">
        {e.fields.map((f) => {
          const lbl = `${t(`md.field.${f.name}`, { defaultValue: f.name })}${f.required ? " *" : ""}`;
          const v = vals[f.name];
          if (f.kind === "bool")
            return <label key={f.name} className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" checked={Boolean(v)} onChange={(x) => set(f.name, x.target.checked)} />{lbl}</label>;
          let input;
          if (f.kind === "choice")
            input = <Select value={String(v)} onChange={(x) => set(f.name, x.target.value)}><option value="">{t("common.choose")}</option>{f.choices.map((c) => <option key={c} value={c}>{label(c)}</option>)}</Select>;
          else if (f.kind === "ref")
            input = <RefSelect f={f} value={String(v)} onChange={(x) => set(f.name, x)} currentLabel={row?.[`${f.name}_label`] as string | undefined} />;
          else if (f.kind === "longtext")
            input = <Textarea value={String(v)} maxLength={f.max_len ?? undefined} onChange={(x) => set(f.name, x.target.value)} />;
          else
            input = <Input type={f.kind === "number" ? "number" : f.kind === "date" ? "date" : "text"} step={f.kind === "number" ? "any" : undefined}
              min={f.min ?? undefined} max={f.max ?? undefined} maxLength={f.max_len ?? undefined} value={String(v)} onChange={(x) => set(f.name, x.target.value)} />;
          return <Field key={f.name} label={lbl} className={f.kind === "longtext" ? "sm:col-span-2" : undefined}>{input}</Field>;
        })}
      </div>
      <div className="mt-3"><FormError error={mut.error} /></div>
      {row && ATTACHABLE.has(e.key) && <div className="mt-4 border-t border-line-soft pt-3"><AttachmentsPanel entity={e.key} entityId={row.id} /></div>}
      {!row && ATTACHABLE.has(e.key) && <p className="mt-3 text-[11.5px] text-fg-3">{t("att.afterSave")}</p>}
    </Modal>
  );
}

function EntityTable({ e }: { e: EntityDef }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [edit, setEdit] = useState<Row | null | "new">(null);
  const rows = useQuery({ queryKey: ["md", "rows", e.key], queryFn: () => api<Row[]>(`/masterdata/${e.key}`) });
  const del = useMutation({ mutationFn: (id: number) => send("DELETE", `/masterdata/${e.key}/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["md"] }) });
  const visible = useMemo(() => (rows.data ?? []).filter((r) => (showInactive || !e.has_active || r.active !== false)
    && (!q || Object.values(r).some((v) => typeof v === "string" && v.toLowerCase().includes(q.toLowerCase())))), [rows.data, q, showInactive, e.has_active]);
  const cols: Column<Row>[] = e.fields.filter((f) => f.kind !== "longtext").map((f) => ({
    key: f.name,
    header: t(`md.field.${f.name}`, { defaultValue: f.name }),
    align: f.kind === "number" ? "right" as const : "left" as const,
    value: (r: Row) => (f.kind === "ref" ? (r[`${f.name}_label`] as string) : (r[f.name] as string | number)),
    render: (r: Row) => {
      const v = r[f.name];
      if (v === null || v === undefined || v === "") return <span className="text-fg-3">—</span>;
      if (f.kind === "ref") return <span>{(r[`${f.name}_label`] as string) ?? v}</span>;
      if (f.kind === "bool") return v ? <Pill tone="good">{t("md.active")}</Pill> : <Pill tone="neutral">{t("md.inactive")}</Pill>;
      if (f.kind === "choice") return label(String(v));
      if (f.kind === "date") return fmtDate(String(v));
      if (f.kind === "number") return <span className="tnum">{fmtNum(Number(v), 3)}</span>;
      return <span className={f.name === "code" ? "font-mono" : undefined}>{String(v)}</span>;
    },
  }));
  if (e.can_edit) cols.push({
    key: "_actions", header: "", render: (r: Row) => (
      <span className="flex gap-2 justify-end">
        <button className="text-fg-3 hover:text-accent" aria-label={t("common.edit")} onClick={() => setEdit(r)}><Pencil size={14} /></button>
        <button className="text-fg-3 hover:text-critical" aria-label={t("md.delete")} onClick={() => {
          if (window.confirm(t("md.confirmDelete"))) del.mutate(r.id);
        }}><Trash2 size={14} /></button>
      </span>
    ),
  });
  return (
    <Card title={t(`md.entity.${e.key}`)} subtitle={t(`md.help.${e.key}`, { defaultValue: "" }) || undefined}
      actions={<Button disabled={!e.can_edit} title={e.can_edit ? undefined : t("auth.noPermission")} onClick={() => setEdit("new")}><Plus size={14} />{t("md.new")}</Button>}>
      <div className="flex flex-wrap gap-3 items-center mb-3">
        <Input placeholder={t("md.search")} value={q} onChange={(x) => setQ(x.target.value)} className="max-w-xs" />
        {e.has_active && <label className="flex items-center gap-2 text-xs text-fg-2"><input type="checkbox" checked={showInactive} onChange={(x) => setShowInactive(x.target.checked)} />{t("md.showInactive")}</label>}
        <span className="text-xs text-fg-3 ml-auto">{visible.length} / {rows.data?.length ?? 0}</span>
      </div>
      <FormError error={del.error} />
      {rows.isPending ? <Loading /> : rows.isError ? <ErrorState error={rows.error} /> : (
        <DataTable rows={visible} rowKey={(r) => r.id} columns={cols} empty={<span className="text-fg-3">{t("md.empty")}</span>} />
      )}
      {edit && <EditModal e={e} row={edit === "new" ? null : edit} onClose={() => setEdit(null)} />}
    </Card>
  );
}

export default function MasterDataPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const schema = useQuery({ queryKey: ["md", "schema"], queryFn: () => api<EntityDef[]>("/masterdata") });
  const current = params.get("entity") ?? "site";
  if (schema.isPending) return <Loading />;
  if (schema.isError) return <ErrorState error={schema.error} />;
  const e = schema.data.find((x) => x.key === current) ?? schema.data[0];
  return (
    <div className="space-y-4">
      <PageHeader title={t("md.title")} subtitle={t("md.subtitle")} />
      <div className="flex flex-wrap gap-x-6 gap-y-2">
        {GROUPS.map((g) => (
          <div key={g} className="flex items-center gap-1 flex-wrap">
            <span className="text-[11px] uppercase tracking-wide text-fg-3 mr-1">{t(`md.group.${g}`)}</span>
            {schema.data.filter((x) => x.group === g).map((x) => (
              <button key={x.key} role="tab" aria-selected={x.key === e.key} onClick={() => setParams({ entity: x.key })}
                className={clsx("px-2.5 py-1 rounded text-sm border", x.key === e.key ? "border-accent bg-accent-soft text-fg" : "border-line text-fg-2 hover:text-fg")}>
                {t(`md.entity.${x.key}`)}
              </button>
            ))}
          </div>
        ))}
      </div>
      <EntityTable key={e.key} e={e} />
    </div>
  );
}
