/**
 * Same-origin proxy from the browser to the FastAPI backend.
 *
 * The browser never sees the backend URL or the API token: the token is injected here, on the
 * server. Paths are validated (no traversal) and only allow-listed headers are forwarded.
 */
import type { NextRequest } from "next/server";

import {
  ProxyPathError,
  buildBackendUrl,
  forwardedRequestHeaders,
  forwardedResponseHeaders,
} from "@/lib/proxy";
import { getServerConfig } from "@/lib/server/config";

const MAX_BODY_BYTES = 1_000_000;
const TIMEOUT_MS = 30_000;

function errorResponse(status: number, code: string, message: string): Response {
  return Response.json(
    { error: { code, message, details: null, request_id: null } },
    { status, headers: { "cache-control": "no-store" } },
  );
}

async function forward(
  request: NextRequest,
  context: RouteContext<"/api/backend/[...path]">,
): Promise<Response> {
  const { path } = await context.params;
  const config = await getServerConfig();

  let target: URL;
  try {
    target = buildBackendUrl(config.backendUrl, config.apiPrefix, path, request.nextUrl.search);
  } catch (error) {
    if (error instanceof ProxyPathError) return errorResponse(400, "bad_request", error.message);
    throw error;
  }

  let body: ArrayBuffer | undefined;
  if (request.method !== "GET" && request.method !== "HEAD") {
    body = await request.arrayBuffer();
    if (body.byteLength > MAX_BODY_BYTES) {
      return errorResponse(413, "payload_too_large", "Request body is too large");
    }
  }

  try {
    const response = await fetch(target, {
      method: request.method,
      headers: forwardedRequestHeaders(request.headers, config.apiToken),
      body,
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    return new Response(response.body, {
      status: response.status,
      headers: forwardedResponseHeaders(response.headers),
    });
  } catch {
    return errorResponse(502, "backend_unreachable", "The backend API is unreachable.");
  }
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
