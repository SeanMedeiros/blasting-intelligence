import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Box, Download, FileText, Lock, Plus, Ruler, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { axisProps, chart } from "../../components/charts/theme";
import { Card, Empty, ErrorState, Loading, PageHeader, Pill, Progress, StatusPill } from "../../components/ui";
import { Button, Field, FormError, Input, Modal, Select, Textarea } from "../../components/ui/forms";
import { api, send, withLang } from "../../lib/api";
import { fmtDate, fmtNum, label } from "../../lib/format";
import { STATUS_COLOR } from "../scanning/colors";
import { addDays, useToday } from "../../lib/dates";
import { useOptions } from "../../lib/options";
import { NewPatternModal, PatternActions } from "../operations/forms";
import { AttachmentsButton, useAttachmentCounts } from "../../components/Attachments";

interface PatternRow {
  id: number; code: string; bench: string; area: string; blast: string | null; blast_status: string | null; planned_blast_date: string | null;
  drilled_on: string | null; holes: number; measured: number; inspected_pct: number | null; deviations: number; deviation_rate_pct: number | null;
  redrill: number; accepted_by_engineer: number; avg_abs_depth_diff_m: number | null; avg_toe_deviation_m: number | null; outstanding: number; water_holes: number;
}
interface HoleRow {
  id: number; hole_code: string; row: number; col: number; planned_x: number; planned_y: number; planned_depth_m: number;
  measured_depth_m: number | null; depth_diff_m: number | null; toe_deviation_m: number | null; collar_offset_m: number | null;
  water_present: boolean | null; hole_condition: string | null; status: string; measured_at: string | null; technician: string | null;
  measurement_count: number; notes: string | null;
}
interface Tol { configured: boolean; depth_min_m: number; depth_max_m: number; toe_deviation_max_m: number; source: string | null; is_demo_placeholder: boolean }
interface PatternDetail {
  id: number; code: string; bench: string; bench_height_m: number; rock_type: string; design_document_ref: string; approved_by: string;
  hole_diameter_mm: number; drilled_on: string | null; blast: { id: number; code: string; status: string; planned_date: string } | null;
  locked: boolean; face_survey_id: number | null;
  approved_loading_records: { document_ref: string; revision: string; approved_by: string; approved_on: string; notes: string }[];
  tolerances: Tol; stats: Omit<PatternRow, "id" | "code" | "bench" | "area" | "blast" | "blast_status" | "planned_blast_date" | "drilled_on">;
  holes: HoleRow[]; capa: { code: string; description: string; status: string; due_date: string; owner: string; overdue: boolean }[];
}
interface HoleDetail extends HoleRow {
  pattern: string;
  history: { id: number; measured_at: string; technician: string; instrument: string | null; measured_depth_m: number; depth_diff_m: number; toe_deviation_m: number | null; collar_offset_m: number; water_present: boolean; hole_condition: string; status: string; notes: string | null }[];
}

const STATUSES = ["WITHIN_TOLERANCE", "OUT_OF_TOLERANCE", "REDRILL_REQUIRED", "ACCEPTED_BY_ENGINEER", "NOT_MEASURED"];
const TONE: Record<string, "good" | "critical" | "serious" | "warning" | "neutral"> = {
  WITHIN_TOLERANCE: "good", OUT_OF_TOLERANCE: "critical", REDRILL_REQUIRED: "serious", ACCEPTED_BY_ENGINEER: "warning", NOT_MEASURED: "neutral",
};
const holePill = (s: string) => <Pill tone={TONE[s] ?? "neutral"}>{label(s)}</Pill>;

/** Plan view of the pattern. Shape + colour encode status so it is never colour-only. */
function PatternMap({ holes, selected, onSelect }: { holes: HoleRow[]; selected: number | null; onSelect: (id: number) => void }) {
  const { t } = useTranslation();
  if (!holes.length) return <Empty>{t("ops.noDesignYet")}</Empty>;
  const xs = holes.map((h) => h.planned_x), ys = holes.map((h) => h.planned_y);
  const [x0, x1, y0, y1] = [Math.min(...xs) - 3, Math.max(...xs) + 3, Math.min(...ys) - 3, Math.max(...ys) + 4];
  const W = 720, scale = W / (x1 - x0), H = (y1 - y0) * scale;
  const px = (x: number) => (x - x0) * scale, py = (y: number) => H - (y - y0) * scale;
  const r = Math.min(11, scale * 0.9);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label="Drill pattern plan">
      <line x1={0} x2={W} y1={py(Math.min(...ys) - 1.75)} y2={py(Math.min(...ys) - 1.75)} stroke="#e8742c" strokeDasharray="6 4" strokeWidth={1.5} />
      <text x={6} y={py(Math.min(...ys) - 1.75) + 14} fill="#e8742c" fontSize={11}>Free face (crest) ▼</text>
      {holes.map((h) => {
        const cx = px(h.planned_x), cy = py(h.planned_y), c = STATUS_COLOR[h.status];
        const sel = h.id === selected;
        const common = { fill: h.status === "NOT_MEASURED" ? "transparent" : c, stroke: sel ? "#ffffff" : c, strokeWidth: sel ? 3 : 1.6 };
        return (
          <g key={h.id} onClick={() => onSelect(h.id)} className="cursor-pointer" role="button" aria-label={`${h.hole_code} ${h.status}`}>
            <title>{`${h.hole_code} — ${label(h.status)}${h.depth_diff_m !== null ? ` · Δdepth ${h.depth_diff_m > 0 ? "+" : ""}${h.depth_diff_m} m` : ""}${h.toe_deviation_m !== null ? ` · toe ${h.toe_deviation_m} m` : ""}`}</title>
            <circle cx={cx} cy={cy} r={r + 6} fill="transparent" />
            {h.status === "OUT_OF_TOLERANCE" || h.status === "REDRILL_REQUIRED" ? (
              <rect x={cx - r * 0.85} y={cy - r * 0.85} width={r * 1.7} height={r * 1.7} transform={`rotate(45 ${cx} ${cy})`} {...common} />
            ) : (
              <circle cx={cx} cy={cy} r={r * 0.85} {...common} />
            )}
            {h.water_present && <circle cx={cx + r} cy={cy - r} r={3} fill="#3987e5" />}
            {r > 9 && <text x={cx} y={cy + r + 11} textAnchor="middle" fontSize={9} fill="#8794a8">{h.hole_code}</text>}
          </g>
        );
      })}
    </svg>
  );
}

function MeasureModal({ hole, onClose }: { hole: HoleRow; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const people = useQuery({ queryKey: ["personnel"], queryFn: () => api<{ items: { id: number; full_name: string; role: string }[] }>("/records/personnel", { limit: 200 }) });
  const instr = useQuery({ queryKey: ["instruments"], queryFn: () => api<{ items: { id: number; code: string; name: string; instrument_type: string }[] }>("/records/instrument", { limit: 200 }) });
  const [f, setF] = useState({ measured_depth_m: "", toe_deviation_m: "", collar_offset_m: "0", water_present: false, hole_condition: "OPEN", technician_id: "3", instrument_id: "", notes: "" });
  const [result, setResult] = useState<{ status: string; reasons: string[] } | null>(null);
  const mut = useMutation({
    mutationFn: () => send<{ status: string; reasons: string[] }>("POST", `/drillholes/holes/${hole.id}/measurements`, {
      measured_depth_m: Number(f.measured_depth_m), toe_deviation_m: f.toe_deviation_m === "" ? null : Number(f.toe_deviation_m),
      collar_offset_m: Number(f.collar_offset_m || 0), water_present: f.water_present, hole_condition: f.hole_condition,
      technician_id: Number(f.technician_id), instrument_id: f.instrument_id ? Number(f.instrument_id) : null, notes: f.notes || null,
    }),
    onSuccess: (r) => { setResult(r); qc.invalidateQueries({ queryKey: ["dh"] }); },
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <Modal title={`${t("dh.recordTitle")} — ${hole.hole_code}`} onClose={onClose}
      footer={result ? <Button onClick={onClose}>{t("common.close")}</Button> : <><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button>
        <Button perm="drillhole.measure" onClick={() => mut.mutate()} disabled={!f.measured_depth_m || mut.isPending}>{t("common.save")}</Button></>}>
      {result ? (
        <div className="space-y-2">
          <div className="flex items-center gap-2">{t("dh.result")}: {holePill(result.status)}</div>
          <ul className="list-disc pl-5 text-fg-2">{result.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="text-fg-3 text-xs">{t("dh.planned")}: <span className="text-fg tnum">{fmtNum(hole.planned_depth_m, 2)} m</span></div>
          <div className="grid grid-cols-3 gap-3">
            <Field label={t("dh.measuredDepth") + " (m)"}><Input type="number" step="0.01" min="0" value={f.measured_depth_m} onChange={set("measured_depth_m")} autoFocus /></Field>
            <Field label={t("dh.toeDev") + " (m)"}><Input type="number" step="0.01" min="0" value={f.toe_deviation_m} onChange={set("toe_deviation_m")} /></Field>
            <Field label={t("dh.collarOffset") + " (m)"}><Input type="number" step="0.01" min="0" value={f.collar_offset_m} onChange={set("collar_offset_m")} /></Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("dh.condition")}>
              <Select value={f.hole_condition} onChange={set("hole_condition")}>
                {["OPEN", "PARTIALLY_BLOCKED", "COLLAPSED"].map((s) => <option key={s} value={s}>{label(s)}</option>)}
              </Select>
            </Field>
            <Field label={t("dh.water")}>
              <label className="flex items-center gap-2 py-1.5"><input type="checkbox" checked={f.water_present} onChange={(e) => setF({ ...f, water_present: e.target.checked })} />{t("dh.waterPresent")}</label>
            </Field>
            <Field label={t("dh.technician")}>
              <Select value={f.technician_id} onChange={set("technician_id")}>
                {people.data?.items.map((p) => <option key={p.id} value={p.id}>{p.full_name} — {p.role}</option>)}
              </Select>
            </Field>
            <Field label={t("dh.instrument")}>
              <Select value={f.instrument_id} onChange={set("instrument_id")}>
                <option value="">—</option>
                {instr.data?.items.filter((i) => i.instrument_type.endsWith("PROBE")).map((i) => <option key={i.id} value={i.id}>{i.code} — {i.name}</option>)}
              </Select>
            </Field>
          </div>
          <Field label={t("dh.notes")}><Textarea value={f.notes} onChange={set("notes")} /></Field>
          <p className="text-[11px] text-fg-3">{t("dh.statusRule")}</p>
          <FormError error={mut.error} />
        </div>
      )}
    </Modal>
  );
}

function AcceptModal({ measurementId, onClose }: { measurementId: number; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [f, setF] = useState({ reviewer_name: "", reviewer_role: "Drill & Blast Engineer", justification: "" });
  const mut = useMutation({
    mutationFn: () => send("POST", `/drillholes/measurements/${measurementId}/engineering-acceptance`, f),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["dh"] }); onClose(); },
  });
  return (
    <Modal title={t("dh.acceptTitle")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button><Button perm="drillhole.accept" onClick={() => mut.mutate()} disabled={mut.isPending}>{t("common.save")}</Button></>}>
      <div className="space-y-3">
        <p className="text-fg-2 text-[13px] rounded border border-warning/40 bg-warning/10 p-2">{t("dh.acceptNote")}</p>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("dh.reviewer")}><Input value={f.reviewer_name} onChange={(e) => setF({ ...f, reviewer_name: e.target.value })} /></Field>
          <Field label={t("dh.reviewerRole")}><Input value={f.reviewer_role} onChange={(e) => setF({ ...f, reviewer_role: e.target.value })} /></Field>
        </div>
        <Field label={t("dh.justification")}><Textarea value={f.justification} onChange={(e) => setF({ ...f, justification: e.target.value })} /></Field>
        <FormError error={mut.error} />
      </div>
    </Modal>
  );
}

function CapaModal({ patternId, onClose }: { patternId: number; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const today = useToday();
  const owners = useOptions("personnel");
  const [f, setF] = useState({ description: "", owner_id: "", due_date: addDays(today, 7) });
  const mut = useMutation({
    mutationFn: () => send("POST", `/drillholes/patterns/${patternId}/capa`, { ...f, owner_id: Number(f.owner_id) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["dh"] }); onClose(); },
  });
  return (
    <Modal title={t("dh.capaTitle")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button><Button perm="capa.create" onClick={() => mut.mutate()} disabled={mut.isPending || !f.owner_id}>{t("common.save")}</Button></>}>
      <div className="space-y-3">
        <Field label={t("dh.capaDesc")}><Textarea value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("dh.owner")}>
            <Select value={f.owner_id} onChange={(e) => setF({ ...f, owner_id: e.target.value })}>
              <option value="">{t("common.choose")}</option>
              {owners.data?.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
            </Select>
          </Field>
          <Field label={t("dh.due")}><Input type="date" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} /></Field>
        </div>
        <FormError error={mut.error} />
      </div>
    </Modal>
  );
}

export default function DrillholesPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const [benchFilter, setBenchFilter] = useState("");
  const [holeId, setHoleId] = useState<number | null>(null);
  const [measuring, setMeasuring] = useState(false);
  const [accepting, setAccepting] = useState<number | null>(null);
  const [capa, setCapa] = useState(false);
  const [newPattern, setNewPattern] = useState(false);

  const patterns = useQuery({ queryKey: ["dh", "patterns"], queryFn: () => api<PatternRow[]>("/drillholes/patterns") });
  const pid = Number(params.get("pattern")) || patterns.data?.find((p) => p.blast_status === "IN_PREPARATION")?.id || patterns.data?.[0]?.id;
  const detail = useQuery({ queryKey: ["dh", "pattern", pid], queryFn: () => api<PatternDetail>(`/drillholes/patterns/${pid}`), enabled: !!pid });
  const d = detail.data;
  const trend = useQuery({ queryKey: ["dh", "trend", d?.bench], queryFn: () => api<{ pattern: string; date: string; deviation_rate_pct: number; avg_toe_deviation_m: number }[]>("/drillholes/trend", { bench: d!.bench }), enabled: !!d });
  const hole = useQuery({ queryKey: ["dh", "hole", holeId], queryFn: () => api<HoleDetail>(`/drillholes/holes/${holeId}`), enabled: !!holeId });
  const benches = Array.from(new Set(patterns.data?.map((p) => p.bench))).sort();
  const shown = patterns.data?.filter((p) => !benchFilter || p.bench === benchFilter) ?? [];
  const sel = d?.holes.find((h) => h.id === holeId) ?? null;
  const depthData = useMemo(() => d?.holes.filter((h) => h.depth_diff_m !== null).map((h) => ({ code: h.hole_code, v: h.depth_diff_m!, toe: h.toe_deviation_m, status: h.status, id: h.id })) ?? [], [d]);
  const tol = d?.tolerances?.configured ? d.tolerances : undefined;
  const patFiles = useAttachmentCounts("drill_pattern", d ? [d.id] : []);
  const counts = useMemo(() => STATUSES.map((s) => [s, d?.holes.filter((h) => h.status === s).length ?? 0] as const), [d]);

  return (
    <div className="space-y-4">
      <PageHeader title={t("dh.title")} subtitle={t("dh.subtitle")}
        right={<Button perm="pattern.manage" onClick={() => setNewPattern(true)}><Plus size={14} />{t("ops.newPattern")}</Button>} />
      {newPattern && <NewPatternModal onClose={() => setNewPattern(false)} onCreated={(id) => { setNewPattern(false); setParams({ pattern: String(id) }); }} />}
      {d && !d.tolerances.configured && (
        <div className="rounded-lg border border-warning/40 bg-warning/10 px-4 py-2.5 text-sm text-warning">{t("ops.tolNotConfigured")} <Link className="underline" to="/settings">{t("nav.settings")}</Link></div>
      )}
      <div className="grid grid-cols-1 xl:grid-cols-[18rem_1fr] gap-4">
        <Card title={t("dh.patterns")} bodyClass="p-0">
          <div className="p-2 border-b border-line-soft">
            <Select value={benchFilter} onChange={(e) => setBenchFilter(e.target.value)} className="text-xs py-1" aria-label={t("scan.bench")}>
              <option value="">{t("scan.allBenches")}</option>
              {benches.map((b) => <option key={b} value={b}>{b}</option>)}
            </Select>
          </div>
          {patterns.isLoading && <Loading />}
          <ul className="max-h-[calc(100vh-14rem)] overflow-y-auto scroll-thin divide-y divide-line-soft">
            {shown.map((p) => (
              <li key={p.id}>
                <button onClick={() => { setParams({ pattern: String(p.id) }); setHoleId(null); }}
                  className={clsx("w-full text-left px-3 py-2 hover:bg-ink-750", p.id === pid && "bg-accent-soft border-l-2 border-accent")}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[12px] truncate">{p.code}</span>
                    {p.blast_status && <StatusPill status={p.blast_status} />}
                  </div>
                  <div className="flex items-center gap-2 mt-1 text-[11px] text-fg-3">
                    <span className="w-20 shrink-0">{fmtDate(p.planned_blast_date)}</span>
                    <Progress value={p.measured} max={p.holes} tone={p.measured === p.holes ? "good" : "info"} />
                    <span className="tnum w-10 text-right">{fmtNum(p.inspected_pct, 0)}%</span>
                  </div>
                  {p.deviations > 0 && <div className={clsx("text-[11px] mt-0.5 tnum", (p.deviation_rate_pct ?? 0) > 10 ? "text-critical" : "text-fg-3")}>{p.deviations} {t("dh.deviationsShort")} ({fmtNum(p.deviation_rate_pct)}%)</div>}
                </button>
              </li>
            ))}
          </ul>
        </Card>

        <div className="space-y-4 min-w-0">
          {detail.error && <ErrorState error={detail.error} />}
          {!d && detail.isLoading && <Loading />}
          {d && (
            <>
              <Card>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-lg font-semibold font-mono">{d.code}</h2>
                      {d.blast && <StatusPill status={d.blast.status} />}
                      {d.locked && <Pill tone="neutral"><Lock size={11} className="inline" /> {t("dh.locked")}</Pill>}
                    </div>
                    <div className="text-xs text-fg-3 mt-1">
                      {d.bench} · {d.rock_type ? `${d.rock_type} · ` : ""}{t("dh.benchHeight")} {fmtNum(d.bench_height_m)} m · Ø {d.hole_diameter_mm} mm · {t("dh.design")}: <span className="font-mono text-fg-2">{d.design_document_ref}</span>
                      {d.blast && <> · {d.blast.code} ({fmtDate(d.blast.planned_date)})</>}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {d.face_survey_id && <Link to={`/scanning?survey=${d.face_survey_id}`}><Button variant="ghost"><Box size={14} />{t("dh.openFace")}</Button></Link>}
                    <a href={withLang(`/api/v1/drillholes/patterns/${d.id}/export.csv`)} download><Button variant="ghost"><Download size={14} />CSV</Button></a>
                    <Button perm="capa.create" variant="ghost" onClick={() => setCapa(true)}><Plus size={14} />{t("dh.newCapa")}</Button>
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-fg-3">
                  <span>{t("ops.drilledOn")}: <span className="text-fg-2">{d.drilled_on ? fmtDate(d.drilled_on) : "—"}</span></span>
                  <span>{t("ops.loadingRefs")}: <span className="text-fg-2 font-mono">{d.approved_loading_records.map((a) => `${a.document_ref} rev ${a.revision}`).join(", ") || "—"}</span></span>
                  <PatternActions p={d} onDeleted={() => setParams({})} />
                  <AttachmentsButton entity="drill_pattern" entityId={d.id} count={patFiles.data?.[String(d.id)]} title={d.code} />
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mt-4">
                  {[
                    [t("dh.kHoles"), fmtNum(d.stats.holes, 0), null],
                    [t("dh.kInspected"), `${fmtNum(d.stats.inspected_pct)}%`, `${d.stats.measured}/${d.stats.holes}`],
                    [t("dh.kDeviations"), fmtNum(d.stats.deviations, 0), d.stats.deviation_rate_pct !== null ? `${fmtNum(d.stats.deviation_rate_pct)}% ${t("dh.ofMeasured")}` : null],
                    [t("dh.kDepth"), d.stats.avg_abs_depth_diff_m !== null ? `${fmtNum(d.stats.avg_abs_depth_diff_m, 2)} m` : "—", t("dh.kDepthSub")],
                    [t("dh.kToe"), d.stats.avg_toe_deviation_m !== null ? `${fmtNum(d.stats.avg_toe_deviation_m, 2)} m` : "—", t("dh.kToeSub")],
                    [t("dh.kOutstanding"), fmtNum(d.stats.outstanding, 0), d.stats.redrill ? `${d.stats.redrill} ${t("dh.redrill")}` : null],
                  ].map(([k, v, s]) => (
                    <div key={k as string} className="rounded border border-line-soft bg-ink-850 p-2.5">
                      <div className="text-[11px] text-fg-3">{k}</div>
                      <div className="text-xl font-semibold tnum">{v}</div>
                      {s && <div className="text-[10.5px] text-fg-3">{s}</div>}
                    </div>
                  ))}
                </div>
              </Card>

              <div className="grid grid-cols-1 2xl:grid-cols-[1fr_24rem] gap-4">
                <Card title={t("dh.planView")} subtitle={t("dh.planHint")}>
                  <PatternMap holes={d.holes} selected={holeId} onSelect={setHoleId} />
                  <div className="flex flex-wrap gap-3 mt-2 text-[11px] text-fg-2">
                    {counts.map(([s, n]) => (
                      <span key={s} className="flex items-center gap-1.5">
                        <svg width="12" height="12" aria-hidden>{s === "OUT_OF_TOLERANCE" || s === "REDRILL_REQUIRED"
                          ? <rect x="2" y="2" width="8" height="8" transform="rotate(45 6 6)" fill={STATUS_COLOR[s]} />
                          : <circle cx="6" cy="6" r="4.5" fill={s === "NOT_MEASURED" ? "none" : STATUS_COLOR[s]} stroke={STATUS_COLOR[s]} strokeWidth="1.5" />}</svg>
                        {label(s)} <span className="tnum text-fg-3">{n}</span>
                      </span>
                    ))}
                    <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-series-1" />{t("dh.waterPresent")}</span>
                  </div>
                </Card>

                <Card title={sel ? `${t("dh.hole")} ${sel.hole_code}` : t("dh.hole")} bodyClass="text-sm">
                  {!sel && <Empty>{t("dh.selectHole")}</Empty>}
                  {sel && (
                    <div className="space-y-3">
                      <div className="flex items-center gap-2">{holePill(sel.status)}</div>
                      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-[12.5px] tnum">
                        <dt className="text-fg-3">{t("dh.planned")}</dt><dd className="text-right">{fmtNum(sel.planned_depth_m, 2)} m</dd>
                        <dt className="text-fg-3">{t("dh.measuredDepth")}</dt><dd className="text-right">{sel.measured_depth_m !== null ? `${fmtNum(sel.measured_depth_m, 2)} m` : "—"}</dd>
                        <dt className="text-fg-3">Δ {t("dh.depth")}</dt><dd className="text-right">{sel.depth_diff_m !== null ? `${sel.depth_diff_m > 0 ? "+" : ""}${fmtNum(sel.depth_diff_m, 2)} m` : "—"}</dd>
                        <dt className="text-fg-3">{t("dh.toeDev")}</dt><dd className="text-right">{sel.toe_deviation_m !== null ? `${fmtNum(sel.toe_deviation_m, 2)} m` : "—"}</dd>
                        <dt className="text-fg-3">{t("dh.collarOffset")}</dt><dd className="text-right">{sel.collar_offset_m !== null ? `${fmtNum(sel.collar_offset_m, 2)} m` : "—"}</dd>
                        <dt className="text-fg-3">{t("dh.condition")}</dt><dd className="text-right">{label(sel.hole_condition)}{sel.water_present ? ` · ${t("dh.water")}` : ""}</dd>
                        <dt className="text-fg-3">{t("dh.verified")}</dt><dd className="text-right">{sel.measured_at ? sel.measured_at.replace("T", " ").slice(0, 16) : "—"}</dd>
                        <dt className="text-fg-3">{t("dh.technician")}</dt><dd className="text-right">{sel.technician ?? "—"}</dd>
                      </dl>
                      {sel.notes && <p className="text-[12px] text-fg-2 border-l-2 border-line pl-2">{sel.notes}</p>}
                      <div className="flex flex-wrap gap-2">
                        <Button perm="drillhole.measure" onClick={() => setMeasuring(true)} disabled={d.locked}><Ruler size={14} />{t("dh.record")}</Button>
                        {hole.data && ["OUT_OF_TOLERANCE", "REDRILL_REQUIRED"].includes(sel.status) && !d.locked && (
                          <Button perm="drillhole.accept" variant="ghost" onClick={() => setAccepting(hole.data!.history[hole.data!.history.length - 1].id)}><ShieldCheck size={14} />{t("dh.accept")}</Button>
                        )}
                      </div>
                      {hole.data && hole.data.history.length > 0 && (
                        <div>
                          <div className="text-[11px] text-fg-3 mb-1">{t("dh.history")} ({hole.data.history.length})</div>
                          <ul className="space-y-1 text-[11.5px] tnum">
                            {hole.data.history.map((x) => (
                              <li key={x.id} className="flex justify-between gap-2 border-b border-line-soft pb-1">
                                <span>{x.measured_at.slice(0, 16).replace("T", " ")} · {x.technician} · {x.instrument ?? "—"}</span>
                                <span>{fmtNum(x.measured_depth_m, 2)} m</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </Card>
              </div>

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <Card title={t("dh.depthChart")} subtitle={tol && t("dh.depthChartSub", { a: fmtNum(tol.depth_min_m, 2), b: fmtNum(tol.depth_max_m, 2) })}>
                  {depthData.length === 0 ? <Empty>{t("dh.noMeasurements")}</Empty> : (
                    <div className="h-56">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={depthData} margin={{ top: 8, right: 8, left: -8, bottom: 0 }} barCategoryGap={1} onClick={(e) => { const p = (e as { activePayload?: { payload: { id: number } }[] })?.activePayload?.[0]?.payload; if (p) setHoleId(p.id); }}>
                          <CartesianGrid stroke={chart.grid} vertical={false} />
                          {tol && <ReferenceArea y1={tol.depth_min_m} y2={tol.depth_max_m} fill="#0ca30c" fillOpacity={0.07} />}
                          <XAxis dataKey="code" {...axisProps} interval="preserveStartEnd" />
                          <YAxis {...axisProps} unit=" m" width={56} domain={[(min: number) => Math.min(-0.9, Math.floor(min * 10) / 10), (max: number) => Math.max(0.6, Math.ceil(max * 10) / 10)]}
                            ticks={[-1.2, -0.9, -0.6, -0.3, 0, 0.3, 0.6, 0.9]} allowDataOverflow={false} />
                          {tol && <ReferenceLine y={tol.depth_min_m} stroke={chart.reference} strokeDasharray="5 4" />}
                          {tol && <ReferenceLine y={tol.depth_max_m} stroke={chart.reference} strokeDasharray="5 4" />}
                          <ReferenceLine y={0} stroke={chart.axis} />
                          <Tooltip cursor={{ fill: "#ffffff08" }} formatter={(v, _n, p) => [`${(v as number) > 0 ? "+" : ""}${fmtNum(v as number, 2)} m · ${label((p.payload as { status: string }).status)}`, "Δ depth"]} />
                          <Bar dataKey="v" isAnimationActive={false} radius={[2, 2, 2, 2]}>
                            {depthData.map((x) => <Cell key={x.id} fill={STATUS_COLOR[x.status]} />)}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  )}
                </Card>
                <Card title={t("dh.trendTitle", { bench: d.bench })} subtitle={t("dh.trendSub")}>
                  {trend.data && trend.data.length > 0 ? (
                    <div className="h-56">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={trend.data.map((x) => ({ ...x, label: fmtDate(x.date) }))} margin={{ top: 8, right: 16, left: -8, bottom: 0 }}>
                          <CartesianGrid stroke={chart.grid} vertical={false} />
                          <XAxis dataKey="label" {...axisProps} />
                          <YAxis {...axisProps} unit="%" domain={[0, (m: number) => Math.max(20, Math.ceil(m / 10) * 10)]} />
                          <ReferenceLine y={5} stroke={chart.reference} strokeDasharray="5 4" label={{ value: `${t("common.target")} ≤ 5% (${t("common.demoTarget")})`, fill: chart.tick, fontSize: 10, position: "insideTopRight" }} />
                          <Tooltip formatter={(v, _n, p) => [`${fmtNum(v as number)} % · ${(p.payload as { pattern: string }).pattern}`, t("kpiNames.drillhole_deviation_rate")]} />
                          <Line type="linear" dataKey="deviation_rate_pct" stroke={chart.series[0]} strokeWidth={2} dot={{ r: 4, fill: chart.series[0], strokeWidth: 0 }} isAnimationActive={false} />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  ) : <Empty>{t("dh.noMeasurements")}</Empty>}
                </Card>
              </div>

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <Card title={t("dh.loadingDoc")}>
                  {d.approved_loading_records.map((a) => (
                    <div key={a.document_ref} className="flex items-start gap-3 text-sm">
                      <FileText size={18} className="text-fg-3 mt-0.5 shrink-0" />
                      <div>
                        <div><span className="font-mono">{a.document_ref}</span> Rev {a.revision} · {a.approved_by} · {a.approved_on}</div>
                        <p className="text-[12px] text-fg-3 mt-1">{a.notes}</p>
                      </div>
                    </div>
                  ))}
                  {tol && <p className="text-[11px] mt-3 text-warning">{t("dh.tolSource")}: {tol.source}</p>}
                </Card>
                <Card title={t("dh.capaList")} bodyClass="p-0">
                  {d.capa.length === 0 && <Empty>{t("common.none")}</Empty>}
                  <ul className="divide-y divide-line-soft">
                    {d.capa.map((c) => (
                      <li key={c.code} className="px-4 py-2 text-sm">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-mono text-[12.5px]">{c.code}</span>
                          <span className="flex gap-1.5">{c.overdue && <Pill tone="critical">{t("dashboard.overdue")}</Pill>}<StatusPill status={c.status} text={label(c.status)} /></span>
                        </div>
                        <p className="text-[12px] text-fg-2 mt-0.5">{c.description}</p>
                        <p className="text-[11px] text-fg-3">{c.owner} · {t("dh.due")} {c.due_date}</p>
                      </li>
                    ))}
                  </ul>
                </Card>
              </div>
            </>
          )}
        </div>
      </div>
      {measuring && sel && <MeasureModal hole={sel} onClose={() => setMeasuring(false)} />}
      {accepting && <AcceptModal measurementId={accepting} onClose={() => setAccepting(null)} />}
      {capa && d && <CapaModal patternId={d.id} onClose={() => setCapa(false)} />}
    </div>
  );
}
