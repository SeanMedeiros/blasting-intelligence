import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldAlert, Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Card, Empty, Loading, PageHeader, Pill, StatusPill } from "../../components/ui";
import { Button, Field, FormError, Input, Textarea } from "../../components/ui/forms";
import { DataTable, Stat } from "../../components/ui/table";
import { api, ApiError, send } from "../../lib/api";
import { fmtDate, label } from "../../lib/format";
import { DetonatorIssueModal } from "../operations/forms";
import { AttachmentsPanel } from "../../components/Attachments";

interface Rec {
  id: number; blast: string; blast_status: string; planned_date: string; approved_plan_ref: string; inventory_lot_ref: string; units_issued: number;
  units_used: number | null; units_returned: number | null; unaccounted: number | null; equipment_ref: string; authorized_personnel: string; procedure_ref: string;
  inspection_status: string; documentation_status: string; verified_by: string | null; verified_at: string | null;
  exceptions: { id: number; raised_at: string; description: string; severity: string; status: string; resolution: string | null }[];
}

function unmetOf(e: unknown) {
  if (e instanceof ApiError) { try { return (JSON.parse(e.message).unmet as string[]) ?? null; } catch { return null; } }
  return null;
}

function Detail({ r }: { r: Rec }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const audit = useQuery({ queryKey: ["det", "audit", r.id], queryFn: () => api<{ at: string; by: string; action: string; detail: string | null }[]>(`/detonators/${r.id}/audit`) });
  const [units, setUnits] = useState({ used: String(r.units_used ?? ""), returned: String(r.units_returned ?? "") });
  const [verifier, setVerifier] = useState("");
  const [resolution, setResolution] = useState("");
  const inv = () => qc.invalidateQueries({ queryKey: ["det"] });
  const upd = useMutation({ mutationFn: () => send("PATCH", `/detonators/${r.id}`, { units_used: Number(units.used), units_returned: Number(units.returned), inspection_done: true }), onSuccess: inv });
  const ver = useMutation({ mutationFn: () => send("POST", `/detonators/${r.id}/verify`, { verified_by: verifier }), onSuccess: inv });
  const close = useMutation({ mutationFn: (id: number) => send("POST", `/traceability-exceptions/${id}/close`, { resolution }), onSuccess: inv });
  const locked = r.documentation_status === "COMPLETE";
  const unmet = unmetOf(ver.error);
  return (
    <div className="space-y-4 text-[12.5px]">
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
        <dt className="text-fg-3">{t("det.plan")}</dt><dd className="font-mono">{r.approved_plan_ref}</dd>
        <dt className="text-fg-3">{t("det.lot")}</dt><dd className="font-mono">{r.inventory_lot_ref}</dd>
        <dt className="text-fg-3">{t("det.equipment")}</dt><dd>{r.equipment_ref}</dd>
        <dt className="text-fg-3">{t("det.personnel")}</dt><dd>{r.authorized_personnel}</dd>
        <dt className="text-fg-3">{t("det.procedure")}</dt><dd className="font-mono">{r.procedure_ref}</dd>
        <dt className="text-fg-3">{t("det.verified")}</dt><dd>{r.verified_by ? `${r.verified_by} · ${r.verified_at?.slice(0, 16).replace("T", " ")}` : "—"}</dd>
      </dl>
      <AttachmentsPanel entity="detonator_record" entityId={r.id} />
      {!locked && (
        <div className="rounded border border-line-soft p-3 space-y-2">
          <div className="text-xs uppercase text-fg-3">{t("det.reconcile")}</div>
          <div className="flex flex-wrap items-end gap-2">
            <Field label={`${t("det.issued")}`}><Input value={r.units_issued} disabled className="w-20" /></Field>
            <Field label={t("det.used")}><Input type="number" min="0" value={units.used} onChange={(e) => setUnits({ ...units, used: e.target.value })} className="w-20" /></Field>
            <Field label={t("det.returned")}><Input type="number" min="0" value={units.returned} onChange={(e) => setUnits({ ...units, returned: e.target.value })} className="w-20" /></Field>
            <Button perm="detonator.record" variant="ghost" onClick={() => upd.mutate()} disabled={units.used === "" || units.returned === ""}>{t("common.save")}</Button>
          </div>
          <FormError error={upd.error} />
          <div className="flex items-end gap-2">
            <Field label={t("det.verifier")}><Input value={verifier} onChange={(e) => setVerifier(e.target.value)} /></Field>
            <Button perm="detonator.verify" onClick={() => ver.mutate()} disabled={verifier.length < 3}>{t("det.verify")}</Button>
          </div>
          {unmet ? <ul className="list-disc pl-5 text-critical">{unmet.map((u) => <li key={u}>{u}</li>)}</ul> : <FormError error={ver.error} />}
        </div>
      )}
      <div>
        <div className="text-xs uppercase text-fg-3 mb-1">{t("det.exceptions")}</div>
        {r.exceptions.length === 0 ? <div className="text-fg-3">{t("common.none")}</div> : r.exceptions.map((x) => (
          <div key={x.id} className="border-l-2 border-critical pl-2 mb-2">
            <div className="flex gap-2 items-center"><Pill tone={x.severity === "HIGH" ? "critical" : "warning"}>{label(x.severity)}</Pill><StatusPill status={x.status === "OPEN" ? "OPEN" : "CLOSED"} text={label(x.status)} /><span className="text-fg-3">{x.raised_at.slice(0, 16).replace("T", " ")}</span></div>
            <div>{x.description}</div>{x.resolution && <div className="text-fg-3">{t("det.resolution")}: {x.resolution}</div>}
            {x.status === "OPEN" && <div className="flex gap-2 mt-1"><Textarea rows={2} value={resolution} onChange={(e) => setResolution(e.target.value)} placeholder={t("det.resolution")} /><Button perm="detonator.verify" variant="ghost" onClick={() => close.mutate(x.id)} disabled={resolution.length < 10}>{t("det.closeException")}</Button></div>}
          </div>
        ))}
        <FormError error={close.error} />
      </div>
      <div>
        <div className="text-xs uppercase text-fg-3 mb-1">{t("det.audit")}</div>
        {audit.isLoading ? <Loading /> : <ol className="border-l border-line ml-1 max-h-64 overflow-y-auto scroll-thin">{audit.data?.map((a, i) => (
          <li key={i} className="ml-3 pb-1.5"><div>{a.action}</div><div className="text-[11px] text-fg-3">{a.at.slice(0, 16).replace("T", " ")} · {a.by}</div>{a.detail && <div className="text-[11px] text-fg-3 truncate" title={a.detail}>{a.detail}</div>}</li>
        ))}</ol>}
      </div>
    </div>
  );
}

export default function DetonatorsPage() {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ["det", "list"], queryFn: () => api<{ records: Rec[]; notice: string }>("/detonators") });
  const [sel, setSel] = useState<number | null>(null);
  const [issuing, setIssuing] = useState(false);
  const recs = q.data?.records ?? [];
  const cur = recs.find((r) => r.id === sel) ?? null;
  return (
    <div className="space-y-4">
      <PageHeader title={t("det.title")} subtitle={t("det.subtitle")}
        right={<Button perm="detonator.record" onClick={() => setIssuing(true)}><Plus size={14} />{t("ops.detIssue")}</Button>} />
      {issuing && <DetonatorIssueModal onClose={() => setIssuing(false)} />}
      <div className="flex gap-2 rounded border border-warning/50 bg-warning/10 p-3 text-[13px]"><ShieldAlert size={18} className="text-warning shrink-0" />{q.data?.notice}</div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label={t("det.records")} value={recs.length} />
        <Stat label={t("det.incomplete")} value={recs.filter((r) => r.documentation_status !== "COMPLETE").length} tone="warning" />
        <Stat label={t("det.openExceptions")} value={recs.reduce((a, r) => a + r.exceptions.filter((x) => x.status === "OPEN").length, 0)} />
        <Stat label={t("det.unreconciled")} value={recs.filter((r) => r.unaccounted !== null && r.unaccounted !== 0).length} />
      </div>
      <div className="grid grid-cols-1 2xl:grid-cols-[1fr_30rem] gap-4">
        <Card title={t("det.list")} bodyClass="p-0">
          {q.isLoading && <Loading />}
          <DataTable rows={recs} rowKey={(r) => r.id} selectedKey={sel} onRowClick={(r) => setSel(r.id)} columns={[
            { key: "blast", header: t("vib.blast"), render: (r) => <span className="font-mono">{r.blast}</span> },
            { key: "planned_date", header: t("lab.date"), render: (r) => fmtDate(r.planned_date) },
            { key: "blast_status", header: t("det.blastStatus"), render: (r) => <StatusPill status={r.blast_status} /> },
            { key: "units_issued", header: t("det.issued"), align: "right" },
            { key: "units_used", header: t("det.used"), align: "right", render: (r) => r.units_used ?? "—" },
            { key: "units_returned", header: t("det.returned"), align: "right", render: (r) => r.units_returned ?? "—" },
            { key: "unaccounted", header: t("det.diff"), align: "right", render: (r) => r.unaccounted === null ? "—" : r.unaccounted === 0 ? <span className="text-good">0</span> : <span className="text-critical font-semibold">{r.unaccounted}</span> },
            { key: "inspection_status", header: t("det.inspection"), render: (r) => label(r.inspection_status) },
            { key: "documentation_status", header: t("det.documentation"), render: (r) => <Pill tone={r.documentation_status === "COMPLETE" ? "good" : "warning"}>{label(r.documentation_status)}</Pill> },
            { key: "exceptions", header: t("det.exceptions"), value: (r) => r.exceptions.length, render: (r) => r.exceptions.length ? <Pill tone={r.exceptions.some((x) => x.status === "OPEN") ? "critical" : "neutral"}>{r.exceptions.length}</Pill> : "—" },
          ]} />
        </Card>
        <Card title={cur ? cur.blast : t("det.detail")}>{cur ? <Detail key={cur.id} r={cur} /> : <Empty>{t("det.select")}</Empty>}</Card>
      </div>
    </div>
  );
}
