"use client";

import { useCallback } from "react";
import { useSWRConfig } from "swr";

/**
 * Workpaper writes change counts shown elsewhere on the page — an area's open/blocking notes, its
 * verification coverage, document verified counts, the graph's footprint. After a write, refetch every
 * cached view that summarises those records (SWR keys are `[path, userId]`).
 */
const COLLAB = ["/api/inbox", "/api/signoffs", "/api/filing", "/api/workpaper/areas", "/api/workpaper/area-summaries"] as const;

export const AFFECTED_BY = {
  note: ["/api/workpaper/notes", ...COLLAB],
  // verifications can reopen sign-offs (withdrawal) and change coverage
  verification: ["/api/verifications", "/api/documents", "/api/values", "/api/graph", ...COLLAB],
  // adjustments change workpaper values, reopen sign-offs and dispose of findings
  adjustment: ["/api/adjustments", "/api/graph", "/api/challenge", ...COLLAB],
  // any inbox decision, judgment, client question or sign-off
  filing: ["/api/filing", "/api/examiner", "/api/notices", "/api/amendments", "/api/engagement", "/api/inbox", "/api/signoffs"],
  collab: ["/api/judgments", "/api/client-questions", "/api/workpaper/notes", "/api/graph", "/api/adjustments", ...COLLAB],
} as const;

/** Uses the cache the component actually reads from (not SWR's global default), so no view is missed. */
export function useRefreshAfter() {
  const { mutate } = useSWRConfig();
  return useCallback((kind: keyof typeof AFFECTED_BY) => {
    const prefixes: readonly string[] = AFFECTED_BY[kind];
    return mutate((key) => Array.isArray(key) && typeof key[0] === "string" && prefixes.some((p) => (key[0] as string).startsWith(p)));
  }, [mutate]);
}
