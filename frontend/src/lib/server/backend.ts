import "server-only";

import type { ApiErrorResponse } from "@/lib/api/types";

import { getServerConfig } from "./config";

export type BackendResult<T> =
  { ok: true; data: T } | { ok: false; status: number | null; message: string };

const TIMEOUT_MS = 10_000;

/** GET a backend API resource from a Server Component. Never throws for HTTP/network errors. */
export async function backendGet<T>(
  path: string,
  params?: Record<string, string | number | undefined>,
): Promise<BackendResult<T>> {
  const config = await getServerConfig();
  const url = new URL(`${config.backendUrl.replace(/\/+$/, "")}${config.apiPrefix}${path}`);
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined) url.searchParams.set(key, String(value));
  }

  const headers = new Headers({ accept: "application/json" });
  if (config.apiToken) headers.set("authorization", `Bearer ${config.apiToken}`);

  let response: Response;
  try {
    response = await fetch(url, {
      headers,
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch {
    return { ok: false, status: null, message: `Backend unreachable at ${config.backendUrl}` };
  }

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorResponse | null;
    return {
      ok: false,
      status: response.status,
      message: body?.error?.message ?? `Backend returned HTTP ${response.status}`,
    };
  }
  return { ok: true, data: (await response.json()) as T };
}
