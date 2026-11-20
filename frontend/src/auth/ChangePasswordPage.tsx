import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Field, FormError, Input } from "../components/ui/forms";
import { api, send, type Me, type Meta } from "../lib/api";
import AuthShell from "./AuthShell";

export function ChangePasswordForm({ user, onDone, onCancel }: { user: Me; onDone: () => void; onCancel?: () => void }) {
  const { t } = useTranslation();
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => api<Meta>("/meta") });
  const [f, setF] = useState({ current: "", next: "", confirm: "" });
  const min = meta.data?.password_min_length ?? 10;
  const mismatch = f.confirm.length > 0 && f.next !== f.confirm;
  const mut = useMutation({
    mutationFn: () => send("POST", "/auth/change-password", { current_password: f.current, new_password: f.next }),
    onSuccess: onDone,
  });
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (!mismatch && f.next) mut.mutate();
      }}
    >
      <input type="hidden" autoComplete="username" value={user.username} readOnly />
      <Field label={t("auth.currentPassword")}>
        <Input type="password" autoComplete="current-password" value={f.current} onChange={(e) => setF({ ...f, current: e.target.value })} />
      </Field>
      <Field label={t("auth.newPassword")} hint={t("auth.policy", { n: min })}>
        <Input type="password" autoComplete="new-password" value={f.next} onChange={(e) => setF({ ...f, next: e.target.value })} />
      </Field>
      <Field label={t("auth.confirmPassword")} hint={mismatch ? <span className="text-critical">{t("auth.mismatch")}</span> : undefined}>
        <Input type="password" autoComplete="new-password" value={f.confirm} onChange={(e) => setF({ ...f, confirm: e.target.value })} />
      </Field>
      <FormError error={mut.error} />
      <div className="flex gap-2 justify-end">
        {onCancel && <Button type="button" variant="ghost" onClick={onCancel}>{t("common.cancel")}</Button>}
        <Button type="submit" disabled={!f.current || f.next.length < min || mismatch || mut.isPending}>{t("auth.changePassword")}</Button>
      </div>
    </form>
  );
}

export default function ChangePasswordPage({ user, onDone, onCancel, forced }: { user: Me; onDone: () => void; onCancel: () => void; forced?: boolean }) {
  const { t } = useTranslation();
  return (
    <AuthShell title={t("auth.changePassword")} subtitle={forced ? t("auth.mustChange", { name: user.full_name }) : undefined}>
      <ChangePasswordForm user={user} onDone={onDone} onCancel={onCancel} />
    </AuthShell>
  );
}
