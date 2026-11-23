import type { components } from "./generated/api";

/**
 * Housing types — generated from the backend OpenAPI document.
 *
 */

type Schemas = components["schemas"];

export type BuildingBrief = Schemas["BuildingBrief"];

export type FloorSummary = Schemas["FloorInBuilding"];

export type RoomInFloor = Schemas["RoomOverview"];

export type BuildingDetail = Schemas["BuildingDetail"];

export type RoomBrief = Schemas["RoomBrief"];

export type BedBrief = Schemas["BedResponse"];

export type RoomDetail = Schemas["RoomDetail"];

export type HousingAssignmentResponse =
  Schemas["HousingAssignmentResponse"];

export type StudentHousingResponse =
  Schemas["StudentHousingResponse"];

export type RoomOverview = Schemas["RoomOverview"];

export type FloorOverview = Schemas["FloorOverview"];

export type HousingOverviewBuilding = Schemas["BuildingOverview"];

export type HousingOverviewResponse = Schemas["HousingOverviewResponse"];

/**
 * Housing import report.
 *
 * Declared here rather than taken from the generated schema because the import
 * endpoints are new: `api.d.ts` is regenerated from a running API, and the UI
 * must compile against the contract it actually calls.
 */
export interface HousingImportRow {
  row_number: number;
  student_number: string | null;
  student_name: string | null;
  building: string | null;
  room: string | null;
  bed: string | null;
  status: "VALID" | "CREATED" | "SKIPPED" | "ERROR";
  code: string | null;
  message: string | null;
}

export interface HousingImportReport {
  dry_run: boolean;
  aborted: boolean;
  total: number;
  valid: number;
  created: number;
  skipped: number;
  failed: number;
  rows: HousingImportRow[];
}
