import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Download, Info, Save, Upload } from "lucide-react";
import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { axisProps, chart } from "../../components/charts/theme";
import { Card, Empty, ErrorState, Loading, PageHeader, Pill, StatusPill } from "../../components/ui";
import { Button, Field, FormError, Input, Modal, Select, Textarea } from "../../components/ui/forms";
import { api, binary, send, upload } from "../../lib/api";
import { fmtNum, label } from "../../lib/format";
import { DIVERGING_STOPS, cssGradient, devColorCss } from "./colors";
import { parseCloud, type FrontRow, type Hole, type Mesh, type Section, type Stats, type SurveyDetail, type SurveySummary } from "./types";
import type { ColorMode, DisplayMode } from "./Viewer3D";
import { useToday } from "../../lib/dates";

const Viewer3D = lazy(() => import("./Viewer3D"));

function Segmented<T extends string>({ value, options, onChange, ariaLabel }: { value: T; options: { v: T; l: string }[]; onChange: (v: T) => void; ariaLabel: string }) {
  return (
    <div className="flex rounded border border-line overflow-hidden text-xs" role="group" aria-label={ariaLabel}>
      {options.map((o) => (
        <button key={o.v} onClick={() => onChange(o.v)} aria-pressed={value === o.v}
          className={clsx("px-2 py-1", value === o.v ? "bg-accent text-ink-950 font-semibold" : "text-fg-2 hover:bg-ink-750")}>
          {o.l}
        </button>
      ))}
    </div>
  );
}

function DeviationLegend({ tol }: { tol: number }) {
  const { t } = useTranslation();
  return (
    <div className="text-[11px] text-fg-3 w-72">
      <div className="h-2.5 rounded" style={{ background: cssGradient(DIVERGING_STOPS) }} />
      <div className="flex justify-between tnum mt-0.5">
        <span>≤ −{fmtNum(2 * tol, 2)}</span><span>−{fmtNum(tol, 2)}</span><span>0</span><span>+{fmtNum(tol, 2)}</span><span>≥ +{fmtNum(2 * tol, 2)} m</span>
      </div>
      <div className="flex justify-between"><span>← {t("scan.behind")}</span><span>{t("scan.inFront")} →</span></div>
    </div>
  );
}

function QualityModal({ survey, onClose }: { survey: SurveyDetail; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [status, setStatus] = useState(survey.quality_status);
  const [notes, setNotes] = useState(survey.quality_notes ?? "");
  const mut = useMutation({
    mutationFn: () => send("PATCH", `/surveys/${survey.id}/quality`, { quality_status: status, quality_notes: notes || null }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["surveys"] }); qc.invalidateQueries({ queryKey: ["survey", survey.id] }); onClose(); },
  });
  return (
    <Modal title={`${t("scan.qualityReview")} — ${survey.code}`} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button><Button perm="survey.write" onClick={() => mut.mutate()} disabled={mut.isPending}>{t("common.save")}</Button></>}>
      <div className="space-y-3">
        <Field label={t("scan.qualityStatus")}>
          <Select value={status} onChange={(e) => setStatus(e.target.value)}>
            {["ACCEPTED", "REVIEW", "REJECTED", "PENDING"].map((s) => <option key={s} value={s}>{label(s)}</option>)}
          </Select>
        </Field>
        <Field label={t("scan.qualityNotes")} hint={status === "REJECTED" ? t("scan.rejectReason") : undefined}>
          <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        <FormError error={mut.error} />
      </div>
    </Modal>
  );
}

function ImportModal({ onClose, onDone }: { onClose: () => void; onDone: (id: number) => void }) {
  const { t } = useTranslation();
  const areas = useQuery({ queryKey: ["areas"], queryFn: () => api<{ items: { id: number; code: string; name: string }[] }>("/records/area") });
  const benches = useQuery({ queryKey: ["benches"], queryFn: () => api<{ items: { id: number; code: string; area_id: number }[] }>("/records/bench") });
  const [file, setFile] = useState<File | null>(null);
  const [area, setArea] = useState("");
  const [bench, setBench] = useState("");
  const [type, setType] = useState("FACE_PROFILE");
  const [date, setDate] = useState(useToday());
  const mut = useMutation({
    mutationFn: () => {
      const f = new FormData();
      f.append("file", file!);
      f.append("area_id", area);
      if (bench) f.append("bench_id", bench);
      f.append("survey_type", type);
      f.append("surveyed_on", date);
      return upload<{ id: number }>("/surveys/import", f);
    },
    onSuccess: (r) => onDone(r.id),
  });
  return (
    <Modal title={t("scan.importTitle")} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>{t("common.cancel")}</Button><Button perm="survey.write" onClick={() => mut.mutate()} disabled={!file || !area || mut.isPending}><Upload size={14} />{mut.isPending ? t("common.loading") : t("scan.import")}</Button></>}>
      <div className="space-y-3">
        <Field label={t("scan.file")} hint={t("scan.importHint")}>
          <Input type="file" accept=".xyz,.csv,.txt,.ply,.las,.laz" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("scan.area")}>
            <Select value={area} onChange={(e) => { setArea(e.target.value); setBench(""); }}>
              <option value="">{t("common.choose")}</option>
              {areas.data?.items.filter((a) => (a as { active?: boolean }).active !== false).map((a) => <option key={a.id} value={a.id}>{a.code} — {a.name}</option>)}
            </Select>
          </Field>
          <Field label={t("scan.bench")}>
            <Select value={bench} onChange={(e) => setBench(e.target.value)}>
              <option value="">—</option>
              {benches.data?.items.filter((b) => String(b.area_id) === area).map((b) => <option key={b.id} value={b.id}>{b.code}</option>)}
            </Select>
          </Field>
          <Field label={t("scan.type")}>
            <Select value={type} onChange={(e) => setType(e.target.value)}>
              {["FACE_PROFILE", "POST_BLAST", "MUCKPILE"].map((s) => <option key={s} value={s}>{label(s)}</option>)}
            </Select>
          </Field>
          <Field label={t("scan.date")}><Input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        </div>
        <FormError error={mut.error} />
      </div>
    </Modal>
  );
}

function SectionChart({ sec, tol }: { sec: Section; tol: number }) {
  const { t } = useTranslation();
  const all = [...sec.survey, ...(sec.reference ?? [])];
  if (!all.length) return <Empty>{t("common.none")}</Empty>;
  const xs = all.map((p) => p[0]);
  const zs = all.map((p) => p[1]);
  const [x0, x1] = [Math.floor(Math.min(...xs)), Math.ceil(Math.max(...xs))];
  const [z0, z1] = [Math.floor(Math.min(...zs)) - 1, Math.ceil(Math.max(...zs)) + 1];
  const aspect = Math.min(4, Math.max(1.2, (x1 - x0) / (z1 - z0)));
  return (
    <div>
      <ResponsiveContainer width="100%" aspect={aspect}>
        <ScatterChart margin={{ top: 8, right: 12, bottom: 18, left: 0 }}>
          <CartesianGrid stroke={chart.grid} />
          <XAxis type="number" dataKey="0" domain={[x0, x1]} {...axisProps} unit=" m" tickCount={8}
            label={{ value: t("scan.horizontal"), position: "insideBottom", offset: -10, fill: chart.tick, fontSize: 11 }} />
          <YAxis type="number" dataKey="1" domain={[z0, z1]} {...axisProps} unit=" m" width={50} />
          <ZAxis range={[4, 4]} />
          <Tooltip cursor={{ stroke: chart.axis }} formatter={(v) => `${fmtNum(v as number, 2)} m`} />
          {sec.holes.map((h) => (
            <ReferenceLine key={h.id} segment={[{ x: h.y, y: h.z }, { x: h.y, y: h.z - h.depth_m }]} stroke="#b6c0cf" strokeWidth={2}
              label={{ value: h.hole_code, position: "top", fill: chart.tick, fontSize: 10 }} />
          ))}
          {sec.reference && <Scatter name={sec.reference_label ?? "Reference"} data={sec.reference} fill={chart.series[1]} isAnimationActive={false} />}
          <Scatter name={t("scan.surveyed")} data={sec.survey} fill={chart.series[0]} isAnimationActive={false} />
        </ScatterChart>
      </ResponsiveContainer>
      <div className="flex flex-wrap gap-4 text-[11px] text-fg-2 mt-1">
        <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full" style={{ background: chart.series[0] }} />{t("scan.surveyed")}</span>
        {sec.reference && <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full" style={{ background: chart.series[1] }} />{sec.reference_label}</span>}
        {sec.holes.length > 0 && <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-fg-2" />{t("scan.plannedHoles")}</span>}
        <span className="text-fg-3">{t("scan.sectionNote", { tol: fmtNum(tol, 2) })}</span>
      </div>
    </div>
  );
}

export default function ScanningPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [typeFilter, setTypeFilter] = useState<string>("");
  const [benchFilter, setBenchFilter] = useState<string>("");
  const [colorMode, setColorMode] = useState<ColorMode>("deviation");
  const [display, setDisplay] = useState<DisplayMode>("points");
  const [showRef, setShowRef] = useState(false);
  const [showHoles, setShowHoles] = useState(true);
  const [pointSize, setPointSize] = useState(0.06);
  const [sectionX, setSectionX] = useState<number | null>(null);
  const [quality, setQuality] = useState(false);
  const [importing, setImporting] = useState(false);

  const list = useQuery({ queryKey: ["surveys"], queryFn: () => api<SurveySummary[]>("/surveys") });
  const sid = Number(params.get("survey")) || list.data?.find((s) => s.bench === "SP-B275" && s.survey_type === "FACE_PROFILE" && s.quality_status === "ACCEPTED")?.id || list.data?.[0]?.id;
  const detail = useQuery({ queryKey: ["survey", sid], queryFn: () => api<SurveyDetail>(`/surveys/${sid}`), enabled: !!sid });
  const [refSel, setRefSel] = useState<string | null>(null);
  useEffect(() => setRefSel(null), [sid]);
  const ref = refSel ?? detail.data?.default_reference ?? "none";

  const cloud = useQuery({ queryKey: ["points", sid, ref], queryFn: async () => parseCloud(await binary(`/surveys/${sid}/points`, { reference: ref })), enabled: !!detail.data, staleTime: Infinity });
  const stats = useQuery({ queryKey: ["stats", sid, ref], queryFn: () => api<Stats>(`/surveys/${sid}/stats`, { reference: ref }), enabled: !!detail.data });
  const mesh = useQuery({ queryKey: ["mesh", sid, ref], queryFn: () => api<Mesh>(`/surveys/${sid}/mesh`, { reference: ref }), enabled: !!detail.data && display !== "points", staleTime: Infinity });
  const isFace = detail.data && !detail.data.imported && detail.data.survey_type !== "POST_BLAST";
  const holes = useQuery({ queryKey: ["holes", sid], queryFn: () => api<Hole[]>(`/surveys/${sid}/holes`), enabled: !!isFace });
  const front = useQuery({ queryKey: ["front", sid], queryFn: () => api<FrontRow>(`/surveys/${sid}/front-row`), enabled: !!isFace });
  const refCloud = useQuery({
    queryKey: ["points", ref, "none"],
    queryFn: async () => parseCloud(await binary(`/surveys/${ref}/points`, { reference: "none" })),
    enabled: showRef && /^\d+$/.test(ref), staleTime: Infinity,
  });
  const xRange = useMemo(() => {
    if (!cloud.data) return null;
    let a = Infinity, b = -Infinity;
    for (let i = 0; i < cloud.data.n; i++) { const x = cloud.data.xyz[3 * i]; if (x < a) a = x; if (x > b) b = x; }
    return [a, b] as const;
  }, [cloud.data]);
  useEffect(() => {
    if (xRange && (sectionX === null || sectionX < xRange[0] || sectionX > xRange[1])) setSectionX(Math.round(((xRange[0] + xRange[1]) / 2) * 2) / 2);
  }, [xRange]); // eslint-disable-line react-hooks/exhaustive-deps
  const section = useQuery({
    queryKey: ["section", sid, ref, sectionX],
    queryFn: () => api<Section>(`/surveys/${sid}/section`, { x: sectionX!, reference: ref }),
    enabled: sectionX !== null && !!detail.data, placeholderData: (p) => p,
  });
  const save = useMutation({
    mutationFn: () => send(`POST`, `/surveys/${sid}/comparisons`, { reference: ref }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["survey", sid] }),
  });
  const tolConfigured = stats.data?.tolerance_m != null;
  const tol = stats.data?.tolerance_m ?? 0.5;  // colour-scale range only when no tolerance is configured
  const benches = Array.from(new Set(list.data?.map((s) => s.bench).filter(Boolean))).sort() as string[];
  const surveys = list.data?.filter((s) => (!typeFilter || s.survey_type === typeFilter) && (!benchFilter || s.bench === benchFilter)) ?? [];
  const d = detail.data;
  const hist = stats.data?.histogram ? stats.data.histogram.counts.map((c, i) => {
    const e = stats.data!.histogram!.edges;
    const mid = (e[i] + e[i + 1]) / 2;
    return { mid, label: fmtNum(mid, 2), c, pct: (100 * c) / (stats.data!.count || 1) };
  }) : [];

  return (
    <div className="space-y-4">
      <PageHeader title={t("scan.title")} subtitle={t("scan.subtitle")}
        right={<Button perm="survey.write" variant="ghost" onClick={() => setImporting(true)}><Upload size={14} />{t("scan.import")}</Button>} />

      <div className="grid grid-cols-1 2xl:grid-cols-[17rem_1fr_21rem] xl:grid-cols-[16rem_1fr] gap-4">
        {/* history */}
        <Card title={t("scan.history")} bodyClass="p-0" className="xl:row-span-2">
          <div className="p-2 flex gap-2 border-b border-line-soft">
            <Select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} aria-label={t("scan.type")} className="text-xs py-1">
              <option value="">{t("scan.allTypes")}</option>
              {["FACE_PROFILE", "POST_BLAST"].map((s) => <option key={s} value={s}>{label(s)}</option>)}
            </Select>
            <Select value={benchFilter} onChange={(e) => setBenchFilter(e.target.value)} aria-label={t("scan.bench")} className="text-xs py-1">
              <option value="">{t("scan.allBenches")}</option>
              {benches.map((b) => <option key={b} value={b}>{b}</option>)}
            </Select>
          </div>
          {list.isLoading && <Loading />}
          <ul className="max-h-[calc(100vh-15rem)] overflow-y-auto scroll-thin divide-y divide-line-soft">
            {surveys.map((s) => (
              <li key={s.id}>
                <button onClick={() => { setParams({ survey: String(s.id) }); }}
                  className={clsx("w-full text-left px-3 py-2 hover:bg-ink-750", s.id === sid && "bg-accent-soft border-l-2 border-accent")}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[12px]">{s.code}</span>
                    <StatusPill status={s.quality_status} />
                  </div>
                  <div className="text-[11px] text-fg-3 mt-0.5">{label(s.survey_type)} · {s.bench ?? s.area} · {s.surveyed_at.slice(0, 10)}</div>
                </button>
              </li>
            ))}
          </ul>
        </Card>

        {/* viewer */}
        <Card bodyClass="p-0" className="min-h-[34rem]">
          <div className="flex flex-wrap items-center gap-2 px-3 py-2 border-b border-line-soft">
            <Segmented ariaLabel={t("scan.colour")} value={colorMode} onChange={setColorMode}
              options={[{ v: "deviation", l: t("scan.deviation") }, { v: "elevation", l: t("scan.elevation") }, { v: "intensity", l: t("scan.intensity") }]} />
            <Segmented ariaLabel={t("scan.display")} value={display} onChange={setDisplay}
              options={[{ v: "points", l: t("scan.points") }, { v: "mesh", l: t("scan.mesh") }, { v: "both", l: t("scan.both") }]} />
            <Select value={ref} onChange={(e) => setRefSel(e.target.value)} className="text-xs py-1 w-auto max-w-[19rem]" aria-label={t("scan.reference")}>
              {d?.references.map((r) => <option key={r.value} value={r.value}>{t("scan.compareWith")}: {r.label}</option>)}
            </Select>
            <label className="flex items-center gap-1 text-xs text-fg-2"><input type="checkbox" checked={showRef} onChange={(e) => setShowRef(e.target.checked)} disabled={ref === "none"} />{t("scan.showReference")}</label>
            {isFace && <label className="flex items-center gap-1 text-xs text-fg-2"><input type="checkbox" checked={showHoles} onChange={(e) => setShowHoles(e.target.checked)} />{t("scan.showHoles")}</label>}
            <label className="flex items-center gap-1 text-xs text-fg-2 ml-auto">{t("scan.pointSize")}
              <input type="range" min={0.02} max={0.15} step={0.01} value={pointSize} onChange={(e) => setPointSize(+e.target.value)} className="w-20 accent-[#e8742c]" />
            </label>
          </div>
          <div className="relative h-[30rem]">
            {(detail.error || cloud.error) && <div className="p-4"><ErrorState error={detail.error ?? cloud.error} /></div>}
            {cloud.isFetching && <div className="absolute inset-0 z-10 flex items-center justify-center bg-ink-950/40"><Loading /></div>}
            {cloud.data && (
              <Suspense fallback={<Loading />}>
                <Viewer3D cloud={cloud.data} mesh={mesh.data} holes={showHoles && isFace ? holes.data : undefined}
                  colorMode={colorMode === "deviation" && !cloud.data.hasDev ? "elevation" : colorMode} display={display} tolerance={tol}
                  sectionX={sectionX} pointSize={pointSize}
                  reference={showRef ? (ref === "design" ? { kind: "design" } : refCloud.data ? { kind: "cloud", cloud: refCloud.data } : null) : null} />
              </Suspense>
            )}
            <div className={clsx("absolute left-3 top-3 rounded bg-ink-950/80 border border-line px-3 py-2 pointer-events-none", !(colorMode === "deviation" && cloud.data?.hasDev) && "hidden")}>
              {colorMode === "deviation" && cloud.data?.hasDev && <DeviationLegend tol={tol} />}
            </div>
          </div>
          {xRange && sectionX !== null && (
            <div className="flex items-center gap-3 px-3 py-2 border-t border-line-soft text-xs text-fg-2">
              <span className="whitespace-nowrap">{t("scan.sectionAt")}</span>
              <input type="range" min={Math.ceil(xRange[0])} max={Math.floor(xRange[1])} step={0.5} value={sectionX}
                onChange={(e) => setSectionX(+e.target.value)} className="flex-1 accent-[#e8742c]" aria-label={t("scan.sectionAt")} />
              <span className="tnum w-16 text-right">x = {fmtNum(sectionX, 1)} m</span>
            </div>
          )}
          {d && (
            <div className="flex flex-wrap justify-between gap-2 px-3 pb-2 text-[11px] text-fg-3 tnum">
              <span>{t("scan.displaying", { shown: fmtNum(d.display_points, 0), total: fmtNum(d.point_count, 0) })}</span>
              <span>{t("scan.controls")}</span>
            </div>
          )}
        </Card>

        {/* metadata & stats */}
        <div className="space-y-4 xl:col-start-2 2xl:col-start-3 2xl:row-start-1">
          <Card title={d?.code ?? t("scan.survey")} actions={d && <Button perm="survey.write" variant="ghost" className="text-xs py-1" onClick={() => setQuality(true)}>{t("scan.qualityReview")}</Button>}>
            {d && (
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12.5px]">
                <dt className="text-fg-3">{t("scan.type")}</dt><dd>{label(d.survey_type)}</dd>
                <dt className="text-fg-3">{t("scan.date")}</dt><dd className="tnum">{d.surveyed_at.replace("T", " ").slice(0, 16)}</dd>
                <dt className="text-fg-3">{t("scan.location")}</dt><dd>{d.area} · {d.bench ?? "—"} {d.blast && <span className="text-fg-3">· {d.blast}</span>}</dd>
                <dt className="text-fg-3">{t("scan.instrument")}</dt><dd className="truncate">{d.instrument ?? "—"}</dd>
                <dt className="text-fg-3">{t("scan.operator")}</dt><dd>{d.operator ?? "—"}</dd>
                <dt className="text-fg-3">{t("scan.spacing")}</dt><dd className="tnum">{d.point_spacing_mm ? `${d.point_spacing_mm} mm` : "—"}</dd>
                <dt className="text-fg-3">{t("scan.registration")}</dt><dd className="tnum">{d.registration_error_mm ? `${d.registration_error_mm} mm` : "—"}</dd>
                <dt className="text-fg-3">{t("scan.crs")}</dt><dd className="text-fg-2">{d.coordinate_system}</dd>
                <dt className="text-fg-3">{t("scan.qualityStatus")}</dt><dd><StatusPill status={d.quality_status} /></dd>
                {d.quality_notes && <><dt className="text-fg-3">{t("scan.qualityNotes")}</dt><dd className="text-fg-2">{d.quality_notes}</dd></>}
              </dl>
            )}
            {d && (
              <div className="flex flex-wrap gap-1.5 mt-3">
                {(["ply", "las", "xyz", "csv", "obj"] as const).map((f) => (
                  <a key={f} href={`/api/v1/surveys/${d.id}/export?fmt=${f}${f !== "obj" ? `&reference=${ref}` : ""}`} download
                    className="inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-[11px] text-fg-2 hover:text-fg hover:border-accent">
                    <Download size={11} /> {f.toUpperCase()}
                  </a>
                ))}
              </div>
            )}
          </Card>

          <Card title={t("scan.deviationStats")} subtitle={stats.data?.reference}
            actions={stats.data?.count ? <Button perm="survey.write" variant="ghost" className="text-xs py-1" onClick={() => save.mutate()} disabled={save.isPending}><Save size={12} />{t("scan.saveComparison")}</Button> : undefined}>
            {stats.isLoading && <Loading />}
            {stats.data && !stats.data.count && <Empty>{t("scan.noComparison")}</Empty>}
            {stats.data?.count ? (
              <>
                <div className="grid grid-cols-3 gap-2 text-center">
                  <div><div className="text-xl font-semibold tnum">{tolConfigured ? `${fmtNum(stats.data.within_tolerance_pct)}%` : "—"}</div><div className="text-[10.5px] text-fg-3">{tolConfigured ? t("scan.within", { tol: fmtNum(tol, 2) }) : t("ops.faceTolMissing")}</div></div>
                  <div><div className="text-xl font-semibold tnum">{fmtNum(stats.data.mean_m, 3)}</div><div className="text-[10.5px] text-fg-3">{t("scan.mean")} (m)</div></div>
                  <div><div className="text-xl font-semibold tnum">{fmtNum(stats.data.std_m, 3)}</div><div className="text-[10.5px] text-fg-3">{t("scan.std")} (m)</div></div>
                </div>
                <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[12px] mt-3 tnum">
                  <dt className="text-fg-3">P5 / P95</dt><dd className="text-right">{fmtNum(stats.data.p05_m, 3)} / {fmtNum(stats.data.p95_m, 3)} m</dd>
                  <dt className="text-fg-3">{t("scan.maxAbs")}</dt><dd className="text-right">{fmtNum(stats.data.max_abs_m, 3)} m</dd>
                  <dt className="text-fg-3">{t("scan.inFrontTol")}</dt><dd className="text-right">{fmtNum(stats.data.above_tolerance_pct)}%</dd>
                  <dt className="text-fg-3">{t("scan.behindTol")}</dt><dd className="text-right">{fmtNum(stats.data.below_tolerance_pct)}%</dd>
                  <dt className="text-fg-3">{t("scan.points")}</dt><dd className="text-right">{fmtNum(stats.data.count, 0)} ({stats.data.region})</dd>
                </dl>
                <div className="h-28 mt-2">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={hist} margin={{ top: 4, right: 4, left: 4, bottom: 0 }} barCategoryGap={1}>
                      <XAxis dataKey="label" {...axisProps} interval={4} />
                      <Tooltip cursor={{ fill: "#ffffff10" }} formatter={(v) => [`${fmtNum(v as number, 1)} %`, t("scan.share")]} labelFormatter={(l) => `${l} m`} />
                      <Bar dataKey="pct" isAnimationActive={false} radius={[2, 2, 0, 0]}>
                        {hist.map((h) => <Cell key={h.mid} fill={devColorCss(h.mid, tol)} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <p className="text-[10.5px] text-fg-3 mt-2 flex gap-1"><Info size={12} className="shrink-0 mt-0.5" />{stats.data.sign_convention}</p>
                {stats.data.tolerance_source && <p className="text-[10.5px] text-warning mt-1">{t("scan.tolSource")}: {stats.data.tolerance_source}</p>}
              </>
            ) : null}
            <FormError error={save.error} />
            {d && d.comparisons.length > 0 && (
              <div className="mt-3 border-t border-line-soft pt-2">
                <div className="text-[11px] text-fg-3 mb-1">{t("scan.savedComparisons")}</div>
                <ul className="space-y-0.5 text-[11.5px] max-h-24 overflow-y-auto scroll-thin">
                  {d.comparisons.map((c) => (
                    <li key={c.id} className="flex justify-between gap-2 tnum"><span className="truncate text-fg-2">{c.reference}</span><span>{fmtNum(c.within_tolerance_pct)}% · {c.computed_by}</span></li>
                  ))}
                </ul>
              </div>
            )}
          </Card>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Card title={t("scan.profileTitle", { x: fmtNum(sectionX ?? 0, 1) })} subtitle={t("scan.profileSub")}>
          {section.data ? <SectionChart sec={section.data} tol={tol} /> : <Loading />}
        </Card>
        <Card title={t("scan.frontRowTitle")} subtitle={front.data?.note ?? t("scan.frontRowNA")} bodyClass="p-0 overflow-x-auto">
          {isFace && front.data && (
            <>
              <table className="w-full text-[12.5px] tnum">
                <thead className="text-[11px] uppercase text-fg-3">
                  <tr className="border-b border-line-soft">
                    <th className="text-left px-3 py-2 font-medium">{t("scan.hole")}</th>
                    <th className="text-right px-2 py-2 font-medium">{t("scan.crest")}</th>
                    <th className="text-right px-2 py-2 font-medium">{t("scan.minimum")}</th>
                    <th className="text-right px-2 py-2 font-medium">{t("scan.toe")}</th>
                    <th className="text-left px-3 py-2 font-medium">{t("scan.check")}</th>
                  </tr>
                </thead>
                <tbody>
                  {front.data.holes.map((h) => (
                    <tr key={h.hole_code} onClick={() => setSectionX(h.x)} className={clsx("border-b border-line-soft cursor-pointer hover:bg-ink-750", Math.abs((sectionX ?? -99) - h.x) < 0.3 && "bg-accent-soft")}>
                      <td className="px-3 py-1.5 font-mono">{h.hole_code} <span className="text-fg-3 text-[11px]">x={fmtNum(h.x, 1)}</span></td>
                      <td className="px-2 py-1.5 text-right">{fmtNum(h.crest_distance_m, 2)}</td>
                      <td className="px-2 py-1.5 text-right">{fmtNum(h.min_distance_m, 2)} <span className="text-fg-3 text-[11px]">@{fmtNum(h.min_at_z_m, 1)}</span></td>
                      <td className="px-2 py-1.5 text-right">{fmtNum(h.toe_distance_m, 2)}</td>
                      <td className="px-3 py-1.5">
                        {h.flags.length === 0 ? <Pill tone="good">{t("scan.inRange")}</Pill> :
                          h.flags.map((f) => <Pill key={f} tone="serious" className="mr-1">{t(`scan.flags.${f}`)}</Pill>)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {front.data.reference && (
                <p className="px-3 py-2 text-[11px] text-fg-3">
                  {t("scan.frontRowRef", { min: fmtNum(front.data.reference.min_distance_m, 2), toe: fmtNum(front.data.reference.toe_distance_max_m, 2) })}
                  {front.data.reference.is_demo_placeholder && <span className="text-warning"> · DEMO PLACEHOLDER</span>}
                </p>
              )}
            </>
          )}
          {!isFace && <Empty>{t("scan.frontRowNA")}</Empty>}
        </Card>
      </div>

      <p className="text-[11px] text-fg-3">{t("scan.limitations")}</p>

      {quality && d && <QualityModal survey={d} onClose={() => setQuality(false)} />}
      {importing && <ImportModal onClose={() => setImporting(false)} onDone={(id) => { setImporting(false); qc.invalidateQueries({ queryKey: ["surveys"] }); setParams({ survey: String(id) }); }} />}
    </div>
  );
}
