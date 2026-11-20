import { useMutation, useQuery } from "@tanstack/react-query";
import { LogIn } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Field, FormError, Input } from "../components/ui/forms";
import { api, send, type Me, type Meta } from "../lib/api";
import AuthShell from "./AuthShell";

export default function LoginPage({ onSignedIn }: { onSignedIn: (u: Me) => void }) {
  const { t } = useTranslation();
  const [f, setF] = useState({ username: "", password: "" });
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => api<Meta>("/meta") });
  const mut = useMutation({
    mutationFn: () => send<{ user: Me }>("POST", "/auth/login", f),
    onSuccess: (r) => onSignedIn(r.user),
  });
  return (
    <AuthShell title={t("auth.signIn")} subtitle={meta.data ? `${meta.data.app} ${meta.data.version}` : undefined}>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (f.username && f.password) mut.mutate();
        }}
      >
        <Field label={t("auth.username")}>
          <Input autoFocus autoComplete="username" name="username" value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} />
        </Field>
        <Field label={t("auth.password")}>
          <Input type="password" autoComplete="current-password" name="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
        </Field>
        <FormError error={mut.error} />
        <Button type="submit" className="w-full justify-center" disabled={!f.username || !f.password || mut.isPending}>
          <LogIn size={14} />
          {t("auth.signIn")}
        </Button>
      </form>
      {meta.data?.mode === "demo" && <p className="text-[11px] text-fg-3 mt-4">{t("auth.demoAccounts")}</p>}
    </AuthShell>
  );
}
