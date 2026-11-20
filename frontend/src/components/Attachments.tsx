import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Ban, FileText, Image as ImageIcon, Paperclip, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, send, upload } from "../lib/api";
import { Button, FormError, Input, Modal } from "./ui/forms";

export interface AttachmentRow {
  id: number; filename: string; content_type: string; size_bytes: number; sha256: string; description: string | null;
  uploaded_by: string; uploaded_at: string; is_image: boolean; voided: boolean; void_reason: string | null; voided_by: string | null;
  voided_at: string | null; url: string; can_void: boolean;
}
interface Types { extensions: string[]; max_mb: number; entities: Record<string, { can_attach: boolean }> }

const size = (b: number) => (b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toFixed(0)} kB` : `${(b / 1048576).toFixed(1)} MB`);
const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });

export function useAttachmentTypes() {
  return useQuery({ queryKey: ["att", "types"], queryFn: () => api<Types>("/attachments/types"), staleTime: 300_000 });
}

/** Evidence files of one record: list (thumbnails for photos), upload, void. Files are never deleted. */
export function AttachmentsPanel({ entity, entityId, compact }: { entity: string; entityId: number; compact?: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const types = useAttachmentTypes();
  const key = ["att", entity, entityId];
  const list = useQuery({ queryKey: key, queryFn: () => api<AttachmentRow[]>("/attachments", { entity, entity_id: entityId }) });
  const [file, setFile] = useState<File | null>(null);
  const [desc, setDesc] = useState("");
  const [voiding, setVoiding] = useState<AttachmentRow | null>(null);
  const [reason, setReason] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const refresh = () => { qc.invalidateQueries({ queryKey: key }); qc.invalidateQueries({ queryKey: ["att", "counts"] }); };
  const up = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      fd.append("entity", entity); fd.append("entity_id", String(entityId)); if (desc) fd.append("description", desc); fd.append("file", file!);
      return upload<AttachmentRow>("/attachments", fd);
    },
    onSuccess: () => { setFile(null); setDesc(""); if (inputRef.current) inputRef.current.value = ""; refresh(); },
  });
  const vd = useMutation({ mutationFn: () => send("POST", `/attachments/${voiding!.id}/void`, { reason }), onSuccess: () => { setVoiding(null); setReason(""); refresh(); } });
  const canAttach = types.data?.entities[entity]?.can_attach ?? false;
  const rows = list.data ?? [];
  return (
    <div className="space-y-2" data-testid={`attachments-${entity}`}>
      {!compact && <div className="flex items-center gap-1.5 text-xs uppercase tracking-wide text-fg-3"><Paperclip size={13} aria-hidden />{t("att.title")} ({rows.filter((r) => !r.voided).length})</div>}
      {rows.length === 0 && <p className="text-[12px] text-fg-3">{t("att.none")}</p>}
      <ul className="space-y-1.5">
        {rows.map((a) => (
          <li key={a.id} className={clsx("flex items-start gap-2 rounded border border-line-soft px-2 py-1.5", a.voided && "opacity-60")}>
            {a.is_image && !a.voided
              ? <a href={`${a.url}?inline=true`} target="_blank" rel="noreferrer" className="shrink-0"><img src={`${a.url}?inline=true`} alt={a.filename} className="w-12 h-12 object-cover rounded" loading="lazy" /></a>
              : <span className="w-12 h-12 shrink-0 grid place-items-center rounded bg-ink-900 text-fg-3">{a.is_image ? <ImageIcon size={18} /> : <FileText size={18} />}</span>}
            <div className="min-w-0 flex-1 text-[12.5px]">
              <a href={a.url} className={clsx("font-medium hover:text-accent break-all", a.voided && "line-through")}>{a.filename}</a>
              <span className="text-fg-3"> · {size(a.size_bytes)}</span>
              {a.description && <div className="text-fg-2">{a.description}</div>}
              <div className="text-[11px] text-fg-3">{a.uploaded_by} · {when(a.uploaded_at)} · <span className="font-mono" title={`SHA-256 ${a.sha256}`}>{a.sha256.slice(0, 10)}…</span></div>
              {a.voided && <div className="text-[11px] text-warning">{t("att.voidedBy", { who: a.voided_by, reason: a.void_reason })}</div>}
            </div>
            {a.can_void && <button className="text-fg-3 hover:text-critical shrink-0" title={t("att.void")} aria-label={t("att.void")} onClick={() => setVoiding(a)}><Ban size={14} /></button>}
          </li>
        ))}
      </ul>
      {canAttach && (
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <input ref={inputRef} type="file" accept={types.data?.extensions.join(",")} onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-[12px] max-w-[15rem]" aria-label={t("att.choose")} />
          <Input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder={t("att.description")} maxLength={300} className="flex-1 min-w-[10rem] py-1 text-xs" />
          <Button variant="ghost" className="py-1 text-xs" onClick={() => up.mutate()} disabled={!file || up.isPending}><Upload size={13} />{up.isPending ? t("att.uploading") : t("att.upload")}</Button>
        </div>
      )}
      {canAttach && <p className="text-[10.5px] text-fg-3">{t("att.accepted", { ext: types.data?.extensions.join(" "), mb: types.data?.max_mb })}</p>}
      <FormError error={up.error} />
      {voiding && (
        <Modal title={`${t("att.void")} — ${voiding.filename}`} onClose={() => setVoiding(null)}
          footer={<><Button variant="ghost" onClick={() => setVoiding(null)}>{t("common.cancel")}</Button><Button variant="danger" onClick={() => vd.mutate()} disabled={reason.length < 5 || vd.isPending}>{t("att.void")}</Button></>}>
          <p className="text-[12.5px] text-fg-2 mb-2">{t("att.voidNote")}</p>
          <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("att.reason")} maxLength={300} />
          <div className="mt-2"><FormError error={vd.error} /></div>
        </Modal>
      )}
    </div>
  );
}

/** Paperclip button with the number of files; opens the panel in a dialog (for rows of a list). */
export function AttachmentsButton({ entity, entityId, count, title }: { entity: string; entityId: number; count?: number; title?: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className={clsx("inline-flex items-center gap-0.5 text-[11px]", count ? "text-accent" : "text-fg-3 hover:text-fg")} onClick={(e) => { e.stopPropagation(); setOpen(true); }}
        aria-label={t("att.title")} title={t("att.title")}><Paperclip size={13} />{count ? count : ""}</button>
      {open && <Modal wide title={`${t("att.title")}${title ? ` — ${title}` : ""}`} onClose={() => setOpen(false)}><AttachmentsPanel entity={entity} entityId={entityId} compact /></Modal>}
    </>
  );
}

/** Valid-attachment counts for many records of one type (badges). */
export function useAttachmentCounts(entity: string, ids: number[]) {
  const key = ids.join(",");
  return useQuery({ queryKey: ["att", "counts", entity, key], queryFn: () => api<Record<string, number>>("/attachments/counts", { entity, ids: key }), enabled: ids.length > 0 });
}
