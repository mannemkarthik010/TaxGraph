/** Where a graph node lives in the rest of the app. */
export function hrefFor(id: string, meta: Record<string, unknown> = {}): string | null {
  if (id.startsWith("line:")) return `/return?line=${encodeURIComponent(String(meta.key))}&v=${meta.version}`;
  if (id.startsWith("ev-")) return `/evidence?doc=${meta.document_id}&page=${meta.page}&ev=${id}`;
  if (id.startsWith("doc:")) return `/evidence?doc=${meta.document_id}&page=${meta.page}`;
  if (/^D\d{2}$/.test(id)) return `/evidence?doc=${id}&page=1`;
  return null;
}

export const proveHref = (ref: string, mode: "up" | "down" | "impact" = "up", version?: string) => {
  const v = version ?? /^line:(v\d+):/.exec(ref)?.[1];
  return `/prove?ref=${encodeURIComponent(ref)}&mode=${mode}${v ? `&v=${v}` : ""}`;
};

/** Where an extracted value goes, read in a specific return version (never silently the current one). */
export const evidenceTraceHref = (ref: string, version: string) =>
  `/prove?ref=${encodeURIComponent(ref)}&mode=down&v=${encodeURIComponent(version)}`;
