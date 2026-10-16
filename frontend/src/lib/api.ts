"use client";

import useSWR, { type SWRConfiguration } from "swr";
import { useActingUser } from "@/lib/user-context";

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
  }
}

export async function apiFetch<T>(
  path: string,
  userId: string,
  init: { method?: string; body?: unknown } = {},
): Promise<T> {
  const res = await fetch(path, {
    method: init.method ?? "GET",
    headers: {
      "X-TaxProof-User": userId,
      ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {}
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

/** SWR keyed by acting user: switching roles refetches everything under the new identity. */
export function useApi<T>(path: string | null, config?: SWRConfiguration<T>) {
  const { userId } = useActingUser();
  return useSWR<T, ApiError>(path ? [path, userId] : null, ([p, u]: [string, string]) => apiFetch<T>(p, u), {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
    ...config,
  });
}

export function useMutate() {
  const { userId } = useActingUser();
  return <T,>(path: string, body?: unknown, method = "POST") => apiFetch<T>(path, userId, { method, body });
}
