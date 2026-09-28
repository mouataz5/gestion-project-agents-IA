import { connection } from "next/server";

/** Liveness probe for the frontend container. */
export async function GET(): Promise<Response> {
  await connection();
  return Response.json(
    { status: "ok", service: "frontend" },
    { headers: { "cache-control": "no-store" } },
  );
}
