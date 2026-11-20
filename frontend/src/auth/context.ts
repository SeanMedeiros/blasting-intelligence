import { createContext, useContext } from "react";
import type { Me } from "../lib/api";

export interface AuthValue {
  user: Me;
  can: (perm: string) => boolean;
  logout: () => Promise<void>;
  refresh: () => Promise<unknown>;
}

export const AuthCtx = createContext<AuthValue | null>(null);

export function useAuth(): AuthValue {
  const v = useContext(AuthCtx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

/** Permission check usable anywhere (outside the provider it allows; the server enforces regardless). */
export function useCan(): (perm: string) => boolean {
  const v = useContext(AuthCtx);
  return v ? v.can : () => true;
}
