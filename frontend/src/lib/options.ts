import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export interface Option { id: number; label: string }

/** Active master-data records as selection options (e.g. "personnel", "area", "instrument"). */
export function useOptions(entity: string) {
  return useQuery({ queryKey: ["md", "options", entity], queryFn: () => api<Option[]>(`/masterdata/${entity}/options`), staleTime: 60_000 });
}
