/**
 * Pure helpers for the `/api/backend/[...path]` route handler, which forwards browser requests to
 * the FastAPI backend and injects the API token on the server side.
 */

export const PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"] as const;

export class ProxyPathError extends Error {}

// Path segments are API words or ids (UUIDs, slugs): nothing that could change the target path.
const SAFE_SEGMENT = /^[A-Za-z0-9_~-][A-Za-z0-9._~-]*$/;
const FORWARDED_REQUEST_HEADERS = ["accept", "content-type", "x-request-id"];
const FORWARDED_RESPONSE_HEADERS = ["content-type", "x-request-id"];

export function buildBackendUrl(
  baseUrl: string,
  apiPrefix: string,
  segments: readonly string[],
  search: string,
): URL {
  let base: URL;
  try {
    base = new URL(baseUrl);
  } catch {
    throw new ProxyPathError("Invalid backend URL");
  }
  if (base.protocol !== "http:" && base.protocol !== "https:") {
    throw new ProxyPathError("Backend URL must use http or https");
  }
  if (segments.length === 0) {
    throw new ProxyPathError("Empty API path");
  }
  for (const segment of segments) {
    if (!SAFE_SEGMENT.test(segment) || segment.includes("..")) {
      throw new ProxyPathError(`Unsafe path segment: ${JSON.stringify(segment)}`);
    }
  }
  const root = base.toString().replace(/\/+$/, "");
  const url = new URL(`${root}${apiPrefix}/${segments.join("/")}${search}`);
  if (url.origin !== base.origin) {
    throw new ProxyPathError("Resolved URL escapes the backend origin");
  }
  return url;
}

export function forwardedRequestHeaders(incoming: Headers, apiToken: string | undefined): Headers {
  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = incoming.get(name);
    if (value) headers.set(name, value);
  }
  // Browser-supplied credentials are never forwarded; only the server-side token is used.
  if (apiToken) headers.set("authorization", `Bearer ${apiToken}`);
  return headers;
}

export function forwardedResponseHeaders(backend: Headers): Headers {
  const headers = new Headers({ "cache-control": "no-store" });
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = backend.get(name);
    if (value) headers.set(name, value);
  }
  return headers;
}
