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

// Candidate profile (Phase 2). Responses use the "-Output" schemas (every field present);
// an Output value is always a valid request body ("-Input").
export type CandidateRead = Schemas["CandidateRead"];
export type CandidateProfile = Schemas["CandidateProfile-Output"];
export type CandidateSkill = Schemas["CandidateSkillRead"];
export type SkillStrength = Schemas["SkillStrength"];
export type LanguageLevel = Schemas["LanguageLevel"];
export type WorkMode = Schemas["WorkMode"];
export type AuthorizationStatus = Schemas["AuthorizationStatus"];
export type SalaryExpectation = Schemas["SalaryExpectation-Output"];
export type SpokenLanguage = Schemas["SpokenLanguage"];
export type TargetCountry = Schemas["TargetCountry-Output"];

// Master CV (Phase 2).
export type CvVersionSummary = Schemas["CvVersionSummary"];
export type CvVersionDetail = Schemas["CvVersionDetail"];
export type CvStatus = Schemas["CvStatus"];
export type ParsedCV = Schemas["ParsedCV-Output"];
export type ExperienceEntry = Schemas["ExperienceEntry-Output"];
export type EducationEntry = Schemas["EducationEntry-Output"];
export type ProjectEntry = Schemas["ProjectEntry-Output"];
export type SkillItem = Schemas["SkillItem-Output"];
export type DateRange = Schemas["DateRange-Output"];
export type YearMonth = Schemas["YearMonth-Output"];

// Jobs and discovery (Phase 3).
export type JobRead = Schemas["JobRead"];
export type JobPage = Schemas["JobPage"];
export type JobDetail = Schemas["JobDetail"];
export type JobListing = Schemas["JobListing"];
export type JobStats = Schemas["JobStats"];
export type JobImportRequest = Schemas["JobImportRequest"];
export type JobImportResult = Schemas["JobImportResult"];
export type JobApplication = Schemas["JobApplicationRead"];
export type JobSource = Schemas["JobSourceRead"];
export type PostingDateStatus = Schemas["PostingDateStatus"];
export type WindowStatus = Schemas["WindowStatus"];
export type PostingWindow = Schemas["WindowRead"];
export type ApplicationStatus = Schemas["ApplicationStatus"];

// Company watchlist (Phase 3).
export type CompanyRead = Schemas["CompanyRead"];
export type CompanyCreate = Schemas["CompanyCreate"];
export type CompanyUpdate = Schemas["CompanyUpdate"];
export type CompanyImportResult = Schemas["CompanyImportResult"];
export type CompanyAtsType = CompanyCreate["ats_type"];

export const POSTING_DATE_STATUSES: readonly PostingDateStatus[] = [
  "KNOWN",
  "ESTIMATED",
  "UNKNOWN",
];
export const COMPANY_ATS_TYPES: readonly CompanyAtsType[] = [
  "GREENHOUSE",
  "LEVER",
  "ASHBY",
  "SMARTRECRUITERS",
  "WORKDAY",
  "GENERIC",
  "OTHER",
];

export const LANGUAGE_LEVELS: readonly LanguageLevel[] = [
  "native",
  "fluent",
  "professional",
  "intermediate",
  "basic",
];
export const WORK_MODES: readonly WorkMode[] = ["onsite", "hybrid", "remote"];
export const AUTHORIZATION_STATUSES: readonly AuthorizationStatus[] = [
  "citizen",
  "permanent_resident",
  "work_permit",
  "other",
];

export const RUN_STATUSES: readonly RunStatus[] = [
  "PENDING",
  "RUNNING",
  "SUCCEEDED",
  "PARTIAL_SUCCESS",
  "FAILED",
  "CANCELLED",
];

export const ACTIVE_RUN_STATUSES: readonly RunStatus[] = ["PENDING", "RUNNING"];
