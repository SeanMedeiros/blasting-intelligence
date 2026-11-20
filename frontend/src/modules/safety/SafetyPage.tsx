import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Card, Loading, PageHeader, Pill, StatusPill } from "../../components/ui";
import { Button, Field, FormError, Input, Modal, Select, Textarea } from "../../components/ui/forms";
import { DataTable, Stat, Tabs } from "../../components/ui/table";
import { api, send } from "../../lib/api";
import { fmtDate, label } from "../../lib/format";
import { nowOn, useToday } from "../../lib/dates";
import { useOptions } from "../../lib/options";
import { AttachmentsButton, AttachmentsPanel, useAttachmentCounts } from "../../components/Attachments";

interface Obs { id: number; code: string; type: string; description: string; observed_at: string; area: string; location: string | null; reported_by: string | null; responsible: string | null; likelihood: number; severity: number; risk_level: string; corrective_action: string | null; status: string; due_date: string | null; overdue: boolean; closure_evidence: string | null }
interface Capa { id: number; code: string; type: string; source_type: string; source_ref: string | null; description: string; owner: string; raised_on: string; due_date: string; status: string; closed_on: string | null; closure_evidence: string | null; overdue: boolean; days_open: number }
interface Insp { id: number; code: string; type: string; blast: string | null; area: string | null; due_date: string; inspected_at: string | null; inspector: string | null; status: string; findings: string | null; items: { id: number; seq: number; text: string; result: string | null; comment: string | null }[] }
interface Matrix { likelihood: string[]; severity: string[]; levels: { name: string; max_score: number }[]; source_document: string; open_counts: { likelihood: number; severity: number; count: number }[] }

const LEVEL_BG: Record<string, string> = { LOW: "bg-series-1/25", MEDIUM: "bg-warning/25", HIGH: "bg-serious/35", CRITICAL: "bg-critical/45" };
const levelFor = (score: number, levels: Matrix["levels"]) => levels.find((l) => score <= l.max_score)?.name ?? "CRITICAL";

function RiskMatrix({ m, onConfigure }: { m: Matrix; onConfigure: () => void }) {
  const { t } = useTranslation();
  const count = (l: number, s: number) => m.open_counts.find((c) => c.likelihood === l && c.severity === s)?.count ?? 0;
  return (
    <div>
      <div className="flex">
        <div className="w-24 flex items-center justify-center -rotate-90 text-[11px] text-fg-3 whitespace-nowrap">{t("qsse.likelihood")} →</div>
        <table className="text-[11px] border-separate border-spacing-0.5">
          <tbody>
            {[5, 4, 3, 2, 1].map((l) => (
              <tr key={l}>
                <td className="pr-2 text-right text-fg-3 whitespace-nowrap">{l} · {m.likelihood[l - 1]}</td>
                {[1, 2, 3, 4, 5].map((s) => {
                  const lv = levelFor(l * s, m.levels); const n = count(l, s);
                  return <td key={s} className={clsx("w-14 h-10 text-center rounded", LEVEL_BG[lv])} title={`${label(lv)} · score ${l * s}`}>
                    <div className="text-fg font-semibold tnum">{n || ""}</div><div className="text-[9.5px] text-fg-2">{l * s}</div></td>;
                })}
              </tr>
            ))}
            <tr><td />{[1, 2, 3, 4, 5].map((s) => <td key={s} className="text-center text-fg-3 pt-1">{s}<div className="text-[9.5px]">{m.severity[s - 1]}</div></td>)}</tr>
          </tbody>
        </table>
      </div>
      <div className="text-center text-[11px] text-fg-3">{t("qsse.severity")} →</div>
      <div className="flex flex-wrap gap-2 mt-2 text-[11px]">
        {m.levels.map((l, i) => <span key={l.name} className="flex items-center gap-1"><span className={clsx("w-3 h-3 rounded", LEVEL_BG[l.name])} />{label(l.name)} ({i === 0 ? 1 : m.levels[i - 1].max_score + 1}–{l.max_score})</span>)}
      </div>
      <div className="flex justify-between items-center mt-2"><span className="text-[10.5px] text-fg-3">{t("qsse.matrixSource")}: {m.source_document}</span><Button perm="safety.configure" variant="ghost" className="text-xs py-1 max-w-[11rem]" onClick={onConfigure}>{t("qsse.configure")}</Button></div>
    </div>
  );
}

function MatrixModal({ m, onClose }: { m: Matrix; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [f, setF] = useState({ low_max: String(m.levels[0].max_score), medium_max: String(m.levels[1].max_score), high_max: String(m.levels[2].max_score), source_document: "" });
  const mut = useMutation({ mutationFn: () => send<{ reclassified_observations: number }>("PUT", "/safety/risk-matrix", { low_max: +f.low_max, medium_max: +f.medium_max, high_max: +f.high_max, source_document: f.source_document }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["qsse"] }); onClose(); } });
  return (
    <Modal title={t("qsse.configure")} onClose={onClose} footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button><Button perm="safety.configure" onClick={() => mut.mutate()}>{t("common.save")}</Button></>}>
      <div className="space-y-3">
        <p className="text-fg-3 text-[12.5px]">{t("qsse.matrixHelp")}</p>
        <div className="grid grid-cols-3 gap-3">
          {(["low_max", "medium_max", "high_max"] as const).map((k) => <Field key={k} label={t(`qsse.${k}`)}><Input type="number" min="1" max="24" value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></Field>)}
        </div>
        <Field label={t("qsse.sourceDoc")}><Input value={f.source_document} onChange={(e) => setF({ ...f, source_document: e.target.value })} /></Field>
        <FormError error={mut.error} />
      </div>
    </Modal>
  );
}

function NewObservation({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const today = useToday();
  const areaOpts = useOptions("area");
  const personOpts = useOptions("personnel");
  const [f, setF] = useState({ obs_type: "HAZARD", description: "", observed_at: nowOn(today), area_id: "", location_detail: "", responsible_id: "", likelihood: "3", severity: "3", corrective_action: "" });
  const [res, setRes] = useState<{ code: string; risk_level: string; capa: string | null } | null>(null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const mut = useMutation({ mutationFn: () => send<typeof res>("POST", "/safety/observations", { ...f, area_id: +f.area_id, responsible_id: +f.responsible_id, likelihood: +f.likelihood, severity: +f.severity, observed_at: f.observed_at + ":00" }), onSuccess: (r) => { setRes(r); qc.invalidateQueries({ queryKey: ["qsse"] }); } });
  return (
    <Modal title={t("qsse.newObs")} onClose={onClose} wide
      footer={res ? <Button onClick={onClose}>{t("common.close")}</Button> : <><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button><Button perm="safety.report" onClick={() => mut.mutate()} disabled={mut.isPending || !f.area_id || !f.responsible_id}>{t("common.save")}</Button></>}>
      {res ? <div className="space-y-2"><div><span className="font-mono">{res.code}</span> · {t("qsse.risk")}: <StatusPill status={res.risk_level} text={label(res.risk_level)} /></div>{res.capa && <div>{t("qsse.capaCreated")}: <span className="font-mono">{res.capa}</span></div>}</div> : (
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("qsse.type")}><Select value={f.obs_type} onChange={set("obs_type")}>{["OBSERVATION", "HAZARD", "NEAR_MISS", "INCIDENT", "POSITIVE"].map((x) => <option key={x} value={x}>{label(x)}</option>)}</Select></Field>
          <Field label={t("qsse.date")}><Input type="datetime-local" value={f.observed_at} onChange={set("observed_at")} /></Field>
          <Field label={t("qsse.description")} className="col-span-2"><Textarea value={f.description} onChange={set("description")} /></Field>
          <Field label={t("scan.area")}><Select value={f.area_id} onChange={set("area_id")}><option value="">{t("common.choose")}</option>{areaOpts.data?.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}</Select></Field>
          <Field label={t("qsse.location")}><Input value={f.location_detail} onChange={set("location_detail")} placeholder="e.g. NP-B310 access ramp" /></Field>
          <Field label={t("qsse.responsible")}><Select value={f.responsible_id} onChange={set("responsible_id")}><option value="">{t("common.choose")}</option>{personOpts.data?.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}</Select></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("qsse.likelihood")}><Select value={f.likelihood} onChange={set("likelihood")}>{[1, 2, 3, 4, 5].map((n) => <option key={n}>{n}</option>)}</Select></Field>
            <Field label={t("qsse.severity")}><Select value={f.severity} onChange={set("severity")}>{[1, 2, 3, 4, 5].map((n) => <option key={n}>{n}</option>)}</Select></Field>
          </div>
          <Field label={t("qsse.action")} className="col-span-2"><Textarea value={f.corrective_action} onChange={set("corrective_action")} /></Field>
          <p className="col-span-2 text-[11px] text-fg-3">{t("qsse.obsRule")}</p>
          <div className="col-span-2"><FormError error={mut.error} /></div>
        </div>
      )}
    </Modal>
  );
}

function CloseModal({ title, path, onClose }: { title: string; path: string; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [ev, setEv] = useState("");
  const mm = path.match(/\/safety\/(observations|capa)\/(\d+)\/close/);
  const target = mm ? { entity: mm[1] === "capa" ? "capa" : "safety_observation", id: Number(mm[2]) } : null;
  const mut = useMutation({ mutationFn: () => send("POST", path, { closure_evidence: ev }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["qsse"] }); onClose(); } });
  return (
    <Modal title={title} onClose={onClose} footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button><Button perm="safety.close" onClick={() => mut.mutate()} disabled={mut.isPending}>{t("qsse.close")}</Button></>}>
      <Field label={t("qsse.evidence")} hint={t("qsse.evidenceHint")}><Textarea value={ev} onChange={(e) => setEv(e.target.value)} /></Field>
      <div className="mt-2"><FormError error={mut.error} /></div>
      {target && <div className="mt-4"><AttachmentsPanel entity={target.entity} entityId={target.id} /></div>}
    </Modal>
  );
}

export default function SafetyPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<"obs" | "capa" | "insp" | "training">("obs");
  const [obsFilter, setObsFilter] = useState("OPEN");
  const [inspType, setInspType] = useState("PRE_BLAST");
  const [newObs, setNewObs] = useState(false);
  const [cfg, setCfg] = useState(false);
  const [closing, setClosing] = useState<{ title: string; path: string } | null>(null);
  const [openInsp, setOpenInsp] = useState<Insp | null>(null);
  const sum = useQuery({ queryKey: ["qsse", "summary"], queryFn: () => api<{ open_observations: number; open_by_risk: Record<string, number>; capa_open: number; capa_overdue: number; inspections_overdue: number; inspections_30d: number; training_expiring: number }>("/safety/summary") });
  const matrix = useQuery({ queryKey: ["qsse", "matrix"], queryFn: () => api<Matrix>("/safety/risk-matrix") });
  const obs = useQuery({ queryKey: ["qsse", "obs", obsFilter], queryFn: () => api<Obs[]>("/safety/observations", { status: obsFilter || undefined }), enabled: tab === "obs" });
  const capa = useQuery({ queryKey: ["qsse", "capa"], queryFn: () => api<Capa[]>("/safety/capa"), enabled: tab === "capa" });
  const obsFiles = useAttachmentCounts("safety_observation", (obs.data ?? []).map((r) => r.id));
  const capaFiles = useAttachmentCounts("capa", (capa.data ?? []).map((r) => r.id));
  const insp = useQuery({ queryKey: ["qsse", "insp", inspType], queryFn: () => api<Insp[]>("/safety/inspections", { inspection_type: inspType }), enabled: tab === "insp" });
  const training = useQuery({ queryKey: ["qsse", "training"], queryFn: () => api<{ id: number; person: string; role: string; course: string; completed_on: string; expires_on: string; certificate_ref: string; status: string }[]>("/safety/training"), enabled: tab === "training" });
  const s = sum.data;
  return (
    <div className="space-y-4">
      <PageHeader title={t("qsse.title")} subtitle={t("qsse.subtitle")} right={<Button perm="safety.report" onClick={() => setNewObs(true)}><Plus size={14} />{t("qsse.newObs")}</Button>} />
      {s && (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          <Stat label={t("dashboard.openObs")} value={s.open_observations} sub={Object.entries(s.open_by_risk).map(([k, v]) => `${label(k)} ${v}`).join(" · ")} />
          <Stat label={t("dashboard.openCapa")} value={s.capa_open} sub={`${s.capa_overdue} ${t("dashboard.overdue")}`} tone={s.capa_overdue ? "critical" : undefined} />
          <Stat label={t("qsse.inspOverdue")} value={s.inspections_overdue} tone={s.inspections_overdue ? "warning" : "good"} />
          <Stat label={t("qsse.insp30")} value={s.inspections_30d} />
          <Stat label={t("qsse.trainingExp")} value={s.training_expiring} tone={s.training_expiring ? "warning" : undefined} />
        </div>
      )}
      <div className="grid grid-cols-1 2xl:grid-cols-[1fr_27rem] gap-4">
        <div className="min-w-0">
          <Tabs value={tab} onChange={setTab} tabs={[{ v: "obs", l: t("qsse.observations") }, { v: "capa", l: t("qsse.capa"), badge: s?.capa_overdue }, { v: "insp", l: t("qsse.inspections"), badge: s?.inspections_overdue }, { v: "training", l: t("qsse.training") }]} />
          {tab === "obs" && (
            <Card bodyClass="p-0" title={t("qsse.observations")} actions={<Select className="text-xs py-1 max-w-[11rem]" value={obsFilter} onChange={(e) => setObsFilter(e.target.value)}><option value="OPEN">{t("qsse.open")}</option><option value="CLOSED">{label("CLOSED")}</option><option value="">{t("qsse.all")}</option></Select>}>
              {obs.isLoading && <Loading />}
              <DataTable rows={obs.data ?? []} rowKey={(r) => r.id} columns={[
                { key: "code", header: "ID", render: (r) => <span className="font-mono">{r.code}</span> },
                { key: "observed_at", header: t("qsse.date"), render: (r) => fmtDate(r.observed_at.slice(0, 10)) },
                { key: "type", header: t("qsse.type"), render: (r) => label(r.type) },
                { key: "description", header: t("qsse.description"), className: "max-w-sm", render: (r) => <div><div>{r.description}</div><div className="text-[11px] text-fg-3">{r.area} · {r.location} · {t("qsse.action")}: {r.corrective_action ?? "—"}</div></div> },
                { key: "responsible", header: t("qsse.responsible") },
                { key: "files", header: "", render: (r) => <AttachmentsButton entity="safety_observation" entityId={r.id} count={obsFiles.data?.[String(r.id)]} title={r.code} /> },
                { key: "risk_level", header: t("qsse.risk"), value: (r) => r.likelihood * r.severity, render: (r) => <StatusPill status={r.risk_level} text={`${label(r.risk_level)} (${r.likelihood}×${r.severity})`} /> },
                { key: "due_date", header: t("dh.due"), render: (r) => <span className={r.overdue ? "text-critical" : ""}>{r.due_date ?? "—"}</span> },
                { key: "status", header: t("lab.status"), render: (r) => r.status === "CLOSED" ? <span title={r.closure_evidence ?? ""}><StatusPill status="COMPLETED" text={label("CLOSED")} /></span> : <Button perm="safety.close" variant="ghost" className="text-xs py-0.5" onClick={() => setClosing({ title: `${t("qsse.close")} ${r.code}`, path: `/safety/observations/${r.id}/close` })}>{t("qsse.close")}</Button> },
              ]} />
            </Card>
          )}
          {tab === "capa" && (
            <Card bodyClass="p-0" title={t("qsse.capa")}>
              {capa.isLoading && <Loading />}
              <DataTable rows={capa.data ?? []} rowKey={(r) => r.id} columns={[
                { key: "code", header: "ID", render: (r) => <span className="font-mono">{r.code}</span> },
                { key: "type", header: t("qsse.type"), render: (r) => label(r.type) },
                { key: "source_type", header: t("qsse.source"), render: (r) => <span>{label(r.source_type)} <span className="font-mono text-fg-3 text-[11px]">{r.source_ref}</span></span> },
                { key: "description", header: t("qsse.description"), className: "max-w-sm" },
                { key: "owner", header: t("dh.owner") },
                { key: "files", header: "", render: (r) => <AttachmentsButton entity="capa" entityId={r.id} count={capaFiles.data?.[String(r.id)]} title={r.code} /> },
                { key: "due_date", header: t("dh.due"), render: (r) => <span className={r.overdue ? "text-critical font-semibold" : ""}>{r.due_date}{r.overdue && ` · ${t("dashboard.overdue")}`}</span> },
                { key: "status", header: t("lab.status"), render: (r) => r.status === "CLOSED" ? <span title={r.closure_evidence ?? ""}><StatusPill status="COMPLETED" text={`${label("CLOSED")} ${r.closed_on}`} /></span> : <Button perm="safety.close" variant="ghost" className="text-xs py-0.5" onClick={() => setClosing({ title: `${t("qsse.close")} ${r.code}`, path: `/safety/capa/${r.id}/close` })}>{t("qsse.close")}</Button> },
              ]} />
            </Card>
          )}
          {tab === "insp" && (
            <Card bodyClass="p-0" title={t("qsse.inspections")} actions={<Select className="text-xs py-1 max-w-[11rem]" value={inspType} onChange={(e) => setInspType(e.target.value)}>{["PRE_BLAST", "PRE_TASK", "PPE"].map((x) => <option key={x} value={x}>{label(x)}</option>)}</Select>}>
              {insp.isLoading && <Loading />}
              <DataTable rows={insp.data ?? []} rowKey={(r) => r.id} onRowClick={setOpenInsp} columns={[
                { key: "code", header: "ID", render: (r) => <span className="font-mono">{r.code}</span> },
                { key: "due_date", header: t("dh.due") },
                { key: "blast", header: t("vib.blast"), render: (r) => r.blast ?? r.area ?? "—" },
                { key: "inspector", header: t("bo.inspector"), render: (r) => r.inspector ?? "—" },
                { key: "status", header: t("lab.status"), render: (r) => <Pill tone={r.status === "COMPLETED" ? "good" : r.status === "OVERDUE" ? "critical" : "neutral"}>{label(r.status)}</Pill> },
                { key: "findings", header: t("qsse.findings"), className: "max-w-xs", render: (r) => <span className="text-fg-2">{r.findings ?? "—"}</span> },
              ]} />
            </Card>
          )}
          {tab === "training" && (
            <Card bodyClass="p-0" title={t("qsse.training")}>
              <DataTable rows={training.data ?? []} rowKey={(r) => r.id} columns={[
                { key: "person", header: t("qsse.person"), render: (r) => <div>{r.person}<div className="text-[11px] text-fg-3">{r.role}</div></div> },
                { key: "course", header: t("qsse.course") },
                { key: "completed_on", header: t("qsse.completed") },
                { key: "expires_on", header: t("qsse.expires") },
                { key: "status", header: t("lab.status"), render: (r) => <Pill tone={r.status === "EXPIRED" ? "critical" : r.status === "EXPIRING" ? "warning" : "good"}>{t(`qsse.tr.${r.status}`)}</Pill> },
              ]} />
            </Card>
          )}
        </div>
        <Card title={t("qsse.matrix")} subtitle={t("qsse.matrixSub")}>{matrix.data ? <RiskMatrix m={matrix.data} onConfigure={() => setCfg(true)} /> : <Loading />}</Card>
      </div>
      <p className="text-[11px] text-fg-3">{t("app.humanControl")}</p>
      {newObs && <NewObservation onClose={() => setNewObs(false)} />}
      {cfg && matrix.data && <MatrixModal m={matrix.data} onClose={() => setCfg(false)} />}
      {closing && <CloseModal {...closing} onClose={() => setClosing(null)} />}
      {openInsp && (
        <Modal title={openInsp.code} onClose={() => setOpenInsp(null)} wide>
          <ul>{openInsp.items.map((i) => <li key={i.id} className="flex gap-2 py-1 border-b border-line-soft text-[13px]"><span className="tnum text-fg-3 w-5">{i.seq}.</span><span className="flex-1">{i.text}</span><span>{i.result ? label(i.result) : "—"}</span></li>)}</ul>
          {openInsp.items.length === 0 && <p className="text-fg-3">{openInsp.findings}</p>}
        </Modal>
      )}
    </div>
  );
}
