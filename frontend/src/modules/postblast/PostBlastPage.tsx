import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { AlertTriangle, ArrowRight, FileDown, GitCompare } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";
import { Card, Empty, Loading, PageHeader, Pill, StatusPill } from "../../components/ui";
import { Button, Field, FormError, Input, Modal, Select, Textarea } from "../../components/ui/forms";
import { DataTable } from "../../components/ui/table";
import { api, ApiError, send, withLang } from "../../lib/api";
import { fmtDate, fmtNum, label } from "../../lib/format";
import { AttachmentsPanel } from "../../components/Attachments";

interface Row { blast_id: number; blast: string; bench: string; fired_at: string | null; stage: string; due_date: string; completed_on: string | null; overdue: boolean; fragmentation_rating: number | null; oversize_observed: boolean | null; engineering_review_status: string; has_proposal: boolean }
interface Detail extends Row {
  review_id: number; rock_type: string; approved_plan_ref: string; stages: string[]; next_requirements: string[]; fields: Record<string, string | null>; engineering_reviewer: string | null; prepared_by: string | null; notice: string;
  collected: {
    drillholes: { holes: number; measured: number; out_of_tolerance: number; deviation_rate_pct: number | null; avg_toe_deviation_m: number | null; water_holes: number };
    checkpoints: { completed: number; total: number };
    vibration: { station: string; ppv_mm_s: number | null; frequency_hz: number | null; limit: number | null; compliance: string; quality: string }[];
    surveys: { id: number; code: string; type: string; quality: string }[];
    survey_comparisons: { survey_id: number; reference: string; within_tolerance_pct: number; mean_m: number }[];
    quality_tests: { code: string; type: string; value: number; unit: string; result: string }[];
    delays: { category: string; hours: number; description: string }[];
    production: { forecast_t: number; actual_t: number | null; variance_pct: number | null };
    inventory: { received: number; used: number; returned: number; balance: number };
    traceability_exceptions: { description: string; status: string }[];
  };
}
const FIELDS = ["plan_compliance", "operational_deviations", "fragmentation_observation", "geology_observation", "lessons_learned", "improvement_proposal"] as const;

function unmetOf(e: unknown) {
  if (e instanceof ApiError) { try { return (JSON.parse(e.message).unmet as string[]) ?? null; } catch { return null; } }
  return null;
}

function EngReview({ id, onClose }: { id: number; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [f, setF] = useState({ reviewer: "", decision: "ACCEPTED", comment: "" });
  const mut = useMutation({ mutationFn: () => send("POST", `/postblast/reviews/${id}/engineering-review`, f), onSuccess: () => { qc.invalidateQueries({ queryKey: ["pb"] }); onClose(); } });
  return (
    <Modal title={t("pb.engReview")} onClose={onClose} footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button><Button perm="postblast.review" onClick={() => mut.mutate()}>{t("common.save")}</Button></>}>
      <div className="space-y-3">
        <p className="text-[13px] rounded border border-warning/40 bg-warning/10 p-2">{t("pb.engNote")}</p>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("dh.reviewer")}><Input value={f.reviewer} onChange={(e) => setF({ ...f, reviewer: e.target.value })} /></Field>
          <Field label={t("pb.decision")}><Select value={f.decision} onChange={(e) => setF({ ...f, decision: e.target.value })}>{["ACCEPTED", "ACCEPTED_WITH_CHANGES", "NOT_ACCEPTED"].map((d) => <option key={d} value={d}>{label(d)}</option>)}</Select></Field>
        </div>
        <Field label={t("dh.justification")}><Textarea value={f.comment} onChange={(e) => setF({ ...f, comment: e.target.value })} /></Field>
        <FormError error={mut.error} />
      </div>
    </Modal>
  );
}

function DetailView({ id }: { id: number }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["pb", id], queryFn: () => api<Detail>(`/postblast/reviews/${id}`) });
  const [form, setForm] = useState<Record<string, string>>({});
  const [rating, setRating] = useState<string>("");
  const [eng, setEng] = useState(false);
  const d = q.data;
  useEffect(() => {
    if (d) { setForm(Object.fromEntries(FIELDS.map((f) => [f, d.fields[f] ?? ""]))); setRating(d.fragmentation_rating ? String(d.fragmentation_rating) : ""); }
  }, [d]);
  const save = useMutation({
    mutationFn: () => send("PATCH", `/postblast/reviews/${id}`, { ...Object.fromEntries(FIELDS.map((f) => [f, form[f] || null])), fragmentation_rating: rating ? Number(rating) : null }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pb"] }),
  });
  const adv = useMutation({ mutationFn: () => send("POST", `/postblast/reviews/${id}/advance`), onSuccess: () => qc.invalidateQueries({ queryKey: ["pb"] }) });
  if (!d) return <Loading />;
  const c = d.collected;
  const idx = d.stages.indexOf(d.stage);
  const locked = d.stage === "COMPLETED";
  const dirty = FIELDS.some((f) => (form[f] ?? "") !== (d.fields[f] ?? "")) || rating !== (d.fragmentation_rating ? String(d.fragmentation_rating) : "");
  const unmet = unmetOf(adv.error);
  return (
    <Card>
      <div className="flex flex-wrap justify-between gap-2">
        <div>
          <div className="flex items-center gap-2"><h2 className="text-lg font-semibold font-mono">{d.blast}</h2>{d.overdue && <Pill tone="critical">{t("dashboard.overdue")}</Pill>}</div>
          <div className="text-xs text-fg-3">{d.bench} · {d.rock_type} · {t("pb.fired")} {d.fired_at?.slice(0, 16).replace("T", " ")} · {t("dh.due")} {d.due_date} · {t("bo.plan")} <span className="font-mono">{d.approved_plan_ref}</span> · {d.prepared_by}</div>
        </div>
        <div className="flex gap-2">
          <Link to={`/blasting?blast=${d.blast_id}`}><Button variant="ghost">{t("pb.openBlast")}</Button></Link>
          <a href={withLang(`/api/v1/reports/blast.pdf?blast_id=${d.blast_id}`)} target="_blank" rel="noreferrer"><Button variant="ghost"><FileDown size={14} />PDF</Button></a>
        </div>
      </div>
      <ol className="flex flex-wrap gap-1 mt-3">
        {d.stages.map((s, i) => <li key={s} className={clsx("flex-1 min-w-[7.5rem] rounded px-2 py-1.5 text-[11px] border", i < idx ? "border-good/40 text-good bg-good/5" : i === idx ? "border-accent bg-accent-soft font-semibold" : "border-line text-fg-3")}><span className="tnum mr-1">{i + 1}.</span>{t(`pb.stage.${s}`)}</li>)}
      </ol>
      {!locked && (
        <div className={clsx("mt-3 rounded border p-3 flex flex-wrap gap-3 items-start", d.next_requirements.length ? "border-warning/50 bg-warning/5" : "border-good/40 bg-good/5")}>
          <div className="flex-1 min-w-[16rem] text-sm">
            <div className="font-medium">{t("bo.nextStep")}: {t(`pb.stage.${d.stages[idx + 1]}`)}</div>
            {d.next_requirements.length ? <ul className="text-[12.5px] text-fg-2 mt-1">{d.next_requirements.map((r) => <li key={r} className="flex gap-1.5"><AlertTriangle size={13} className="text-warning mt-0.5 shrink-0" />{r}</li>)}</ul> : <div className="text-[12.5px] text-good">{t("bo.ready")}</div>}
            {dirty && <div className="text-[11.5px] text-warning mt-1">{t("pb.saveFirst")}</div>}
          </div>
          <Button perm="postblast.edit" onClick={() => adv.mutate()} disabled={d.next_requirements.length > 0 || dirty || adv.isPending}><ArrowRight size={14} />{t("pb.advance")}</Button>
          {unmet && <ul className="w-full text-[12px] text-critical list-disc pl-5">{unmet.map((u) => <li key={u}>{u}</li>)}</ul>}
        </div>
      )}

      <h3 className="text-xs uppercase tracking-wide text-fg-3 mt-5 mb-2">{t("pb.collected")}</h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-[12.5px]">
        <div className="rounded border border-line-soft p-3"><div className="text-fg-3 text-[11px] mb-1">{t("nav.drillholes")}</div>
          <div>{c.drillholes.measured}/{c.drillholes.holes} {t("bo.measured")}</div><div>{c.drillholes.out_of_tolerance} {t("dashboard.outOfTol")} ({fmtNum(c.drillholes.deviation_rate_pct)}%)</div>
          <div>{t("dh.kToe")}: {fmtNum(c.drillholes.avg_toe_deviation_m, 2)} m · {t("dh.water")}: {c.drillholes.water_holes}</div></div>
        <div className="rounded border border-line-soft p-3"><div className="text-fg-3 text-[11px] mb-1">{t("nav.vibration")}</div>
          {c.vibration.map((v) => <div key={v.station} className="flex items-center justify-between gap-2 whitespace-nowrap py-0.5"><span className="w-10">{v.station}</span><span className="tnum flex-1 text-right">{fmtNum(v.ppv_mm_s, 2)} mm/s</span><Pill tone={v.compliance === "EXCEEDANCE" ? "critical" : v.compliance === "COMPLIANT" ? "good" : "neutral"}>{label(v.compliance)}</Pill></div>)}
          {c.vibration.length === 0 && <div className="text-fg-3">{t("common.none")}</div>}</div>
        <div className="rounded border border-line-soft p-3"><div className="text-fg-3 text-[11px] mb-1">{t("nav.scanning")}</div>
          {c.surveys.map((s) => <div key={s.id}><Link to={`/scanning?survey=${s.id}`} className="font-mono text-accent hover:underline">{s.code}</Link> · {label(s.quality)}</div>)}
          {c.survey_comparisons.map((x, i) => <div key={i} className="text-fg-3">{x.reference}: {fmtNum(x.within_tolerance_pct)}% {t("pb.inTol")}</div>)}
          {!c.surveys.some((s) => s.type === "POST_BLAST") && <div className="text-warning">{t("pb.noPostSurvey")}</div>}</div>
        <div className="rounded border border-line-soft p-3"><div className="text-fg-3 text-[11px] mb-1">{t("pb.prodQuality")}</div>
          <div>{t("bo.forecast")} {fmtNum(c.production.forecast_t, 0)} t · {t("bo.actual")} {fmtNum(c.production.actual_t, 0)} t ({c.production.variance_pct !== null ? `${c.production.variance_pct > 0 ? "+" : ""}${fmtNum(c.production.variance_pct)}%` : "—"})</div>
          {c.quality_tests.map((q) => <div key={q.code}>{label(q.type)} {fmtNum(q.value, 3)} {q.unit} · {label(q.result)}</div>)}
          <div>{t("bo.delays")}: {c.delays.reduce((a, x) => a + x.hours, 0)} h {c.delays.map((x) => label(x.category)).join(", ")}</div>
          {c.traceability_exceptions.length > 0 && <div className="text-warning">{c.traceability_exceptions.length} {t("det.exceptions").toLowerCase()}</div>}</div>
      </div>

      <h3 className="text-xs uppercase tracking-wide text-fg-3 mt-5 mb-2">{t("pb.analysis")}</h3>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {FIELDS.map((f) => (
          <Field key={f} label={t(`pb.f.${f}`)} hint={f === "improvement_proposal" ? t("pb.proposalHint") : undefined}>
            <Textarea rows={3} value={form[f] ?? ""} disabled={locked} onChange={(e) => setForm({ ...form, [f]: e.target.value })} />
          </Field>
        ))}
        <Field label={t("pb.rating")} hint={t("pb.ratingHint")}>
          <Select value={rating} disabled={locked} onChange={(e) => setRating(e.target.value)}><option value="">—</option>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n} — {t(`pb.r${n}`)}</option>)}</Select>
        </Field>
        <div className="flex items-end gap-2">
          {!locked && <Button perm="postblast.edit" onClick={() => save.mutate()} disabled={!dirty || save.isPending}>{t("common.save")}</Button>}
          <div className="text-[12.5px]">
            {t("pb.engStatus")}: <Pill tone={d.engineering_review_status === "REVIEWED" ? "good" : d.engineering_review_status === "PENDING" ? "warning" : "neutral"}>{label(d.engineering_review_status)}</Pill>
            {d.engineering_reviewer && <div className="text-[11.5px] text-fg-3 mt-0.5">{d.engineering_reviewer}</div>}
          </div>
          {d.engineering_review_status === "PENDING" && !dirty && <Button perm="postblast.review" variant="ghost" onClick={() => setEng(true)}>{t("pb.recordEng")}</Button>}
        </div>
      </div>
      <FormError error={save.error} />
      <div className="mt-4"><AttachmentsPanel entity="post_blast_review" entityId={d.review_id} /></div>
      <p className="text-[11px] text-fg-3 mt-3">{d.notice}</p>
      {eng && <EngReview id={d.blast_id} onClose={() => setEng(false)} />}
    </Card>
  );
}

type Cmp = { blast: string; bench: string; rock_type: string; fired: string; holes: number; deviation_rate_pct: number | null; avg_toe_deviation_m: number | null; water_holes: number; max_ppv_mm_s: number | null; exceedances: number; fragmentation_rating: number | null; oversize_observed: boolean | null; delay_hours: number; tonnes_variance_pct: number | null; face_within_tolerance_pct: number | null; stage: string };

export default function PostBlastPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const list = useQuery({ queryKey: ["pb", "list"], queryFn: () => api<{ stages: string[]; reviews: Row[] }>("/postblast/reviews") });
  const [cmp, setCmp] = useState<number[]>([]);
  const [showCmp, setShowCmp] = useState(false);
  const rows = list.data?.reviews ?? [];
  const sel = Number(params.get("blast")) || rows.find((r) => r.overdue)?.blast_id || rows[0]?.blast_id;
  const comparison = useQuery({ queryKey: ["pb", "cmp", cmp.join(",")], queryFn: () => api<Cmp[]>("/postblast/compare", { blasts: cmp.join(",") }), enabled: showCmp && cmp.length >= 2 });
  const metrics: [string, (x: Cmp) => string][] = [
    [t("scan.bench"), (x) => `${x.bench} · ${x.rock_type}`], [t("pb.fired"), (x) => x.fired], [t("dh.kHoles"), (x) => String(x.holes)],
    [t("kpiNames.drillhole_deviation_rate"), (x) => `${fmtNum(x.deviation_rate_pct)}%`], [t("dh.kToe"), (x) => `${fmtNum(x.avg_toe_deviation_m, 2)} m`],
    [t("dh.water"), (x) => String(x.water_holes)], [t("pb.maxPpv"), (x) => `${fmtNum(x.max_ppv_mm_s, 2)} mm/s`], [t("dashboard.exceedance"), (x) => String(x.exceedances)],
    [t("pb.faceTol"), (x) => (x.face_within_tolerance_pct !== null ? `${fmtNum(x.face_within_tolerance_pct)}%` : "—")],
    [t("pb.rating"), (x) => (x.fragmentation_rating ? `${x.fragmentation_rating}/5` : "—")], [t("pb.oversize"), (x) => (x.oversize_observed ? "✓" : "—")],
    [t("bo.delays"), (x) => `${x.delay_hours} h`], [t("pb.tonnesVar"), (x) => (x.tonnes_variance_pct !== null ? `${fmtNum(x.tonnes_variance_pct)}%` : "—")], [t("pb.stageCol"), (x) => t(`pb.stage.${x.stage}`)],
  ];
  return (
    <div className="space-y-4">
      <PageHeader title={t("pb.title")} subtitle={t("pb.subtitle")}
        right={<Button variant="ghost" onClick={() => setShowCmp(true)} disabled={cmp.length < 2}><GitCompare size={14} />{t("pb.compare")} ({cmp.length})</Button>} />
      <div className="grid grid-cols-1 2xl:grid-cols-[34rem_1fr] gap-4">
        <Card title={t("pb.reviews")} bodyClass="p-0">
          {list.isLoading && <Loading />}
          <DataTable rows={rows} rowKey={(r) => r.blast_id} selectedKey={sel} onRowClick={(r) => setParams({ blast: String(r.blast_id) })} pageSize={15} columns={[
            { key: "cmp", header: "⇄", render: (r) => <input type="checkbox" aria-label={`compare ${r.blast}`} checked={cmp.includes(r.blast_id)} onClick={(e) => e.stopPropagation()} onChange={() => setCmp((c) => c.includes(r.blast_id) ? c.filter((x) => x !== r.blast_id) : c.length >= 4 ? c : [...c, r.blast_id])} /> },
            { key: "blast", header: t("vib.blast"), render: (r) => <span className="font-mono">{r.blast}</span> },
            { key: "bench", header: t("scan.bench") },
            { key: "fired_at", header: t("pb.fired"), render: (r) => fmtDate(r.fired_at?.slice(0, 10)) },
            { key: "stage", header: t("pb.stageCol"), render: (r) => r.stage === "COMPLETED" ? <StatusPill status="COMPLETED" text={t("pb.stage.COMPLETED")} /> : <Pill tone={r.overdue ? "critical" : "info"}>{t(`pb.stage.${r.stage}`)}</Pill> },
            { key: "fragmentation_rating", header: t("pb.ratingShort"), align: "right", render: (r) => r.fragmentation_rating ?? "—" },
          ]} />
        </Card>
        {sel ? <DetailView key={sel} id={sel} /> : <Empty>{t("common.none")}</Empty>}
      </div>
      {showCmp && (
        <Modal title={t("pb.comparison")} onClose={() => setShowCmp(false)} wide>
          {comparison.isLoading ? <Loading /> : comparison.data && (
            <table className="w-full text-[12.5px] tnum">
              <thead><tr className="border-b border-line"><th />{comparison.data.map((x) => <th key={x.blast} className="text-right px-2 py-1 font-mono">{x.blast}</th>)}</tr></thead>
              <tbody>{metrics.map(([k, f]) => <tr key={k} className="border-b border-line-soft"><td className="py-1 text-fg-3">{k}</td>{comparison.data!.map((x) => <td key={x.blast} className="text-right px-2">{f(x)}</td>)}</tr>)}</tbody>
            </table>
          )}
          <p className="text-[11px] text-fg-3 mt-3">{t("pb.compareNote")}</p>
        </Modal>
      )}
    </div>
  );
}
