import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, type ReactNode } from "react";
import { ApiError, api, send, UNAUTHORIZED_EVENT, type Me } from "../lib/api";
import ChangePasswordPage from "./ChangePasswordPage";
import LoginPage from "./LoginPage";
import { AuthCtx, type AuthValue } from "./context";

async function fetchMe(): Promise<Me | null> {
  try {
    return await api<Me>("/auth/me");
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return null;
    throw e;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["auth", "me"], queryFn: fetchMe, staleTime: 5 * 60_000, retry: false });

  useEffect(() => {
    const on = () => qc.setQueryData(["auth", "me"], null);
    window.addEventListener(UNAUTHORIZED_EVENT, on);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, on);
  }, [qc]);

  const signedIn = useCallback(
    (u: Me) => {
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" && q.queryKey[0] !== "meta" });
      qc.setQueryData(["auth", "me"], u);
    },
    [qc],
  );

  const logout = useCallback(async () => {
    try {
      await send("POST", "/auth/logout");
    } catch {
      /* session already gone */
    }
    qc.setQueryData(["auth", "me"], null);
    qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" && q.queryKey[0] !== "meta" });
  }, [qc]);

  if (me.isPending) {
    return <div className="h-screen grid place-items-center text-fg-3 text-sm">…</div>;
  }
  if (me.isError) {
    return (
      <div className="h-screen grid place-items-center text-sm text-critical p-6 text-center">
        {(me.error as Error).message}
      </div>
    );
  }
  if (!me.data) return <LoginPage onSignedIn={signedIn} />;
  if (me.data.must_change_password) return <ChangePasswordPage user={me.data} forced onDone={() => me.refetch()} onCancel={logout} />;

  const perms = new Set(me.data.permissions);
  const value: AuthValue = { user: me.data, can: (p) => perms.has(p), logout, refresh: () => me.refetch() };
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}
