import "server-only";

import { connection } from "next/server";

export interface ServerConfig {
  /** How the Next.js server reaches the FastAPI backend (e.g. http://backend:8000 in Compose). */
  backendUrl: string;
  apiPrefix: string;
  /** Bearer token for the backend API. Server-side only: never sent to the browser. */
  apiToken: string | undefined;
}

/**
 * Reads configuration at request time. `connection()` makes sure environment variables are not
 * frozen into the build output, so one image works with any backend URL and token.
 */
export async function getServerConfig(): Promise<ServerConfig> {
  await connection();
  return {
    backendUrl: process.env.BACKEND_INTERNAL_URL || "http://localhost:8000",
    apiPrefix: process.env.API_PREFIX || "/api/v1",
    apiToken: process.env.API_AUTH_TOKEN || undefined,
  };
}
