/**
 * API types generated from the backend OpenAPI schema (`make openapi` regenerates schema.d.ts).
 */
import type { components } from "./schema";

type Schemas = components["schemas"];

export type ApiErrorResponse = Schemas["ErrorResponse"];
export type ComponentHealth = Schemas["ComponentHealth"];
export type PhaseInfo = Schemas["PhaseInfo"];
export type RunCreated = Schemas["RunCreated"];
export type RunDetail = Schemas["RunDetail"];
export type RunEvent = Schemas["RunEventOut"];
export type RunPage = Schemas["RunPage"];
export type RunSummary = Schemas["RunSummary"];
export type SystemInfo = Schemas["SystemInfo"];
export type SystemStatus = Schemas["SystemStatus"];

export type RunStatus = RunSummary["status"];

export const RUN_STATUSES: readonly RunStatus[] = [
  "PENDING",
  "RUNNING",
  "SUCCEEDED",
  "PARTIAL_SUCCESS",
  "FAILED",
  "CANCELLED",
];

export const ACTIVE_RUN_STATUSES: readonly RunStatus[] = ["PENDING", "RUNNING"];
