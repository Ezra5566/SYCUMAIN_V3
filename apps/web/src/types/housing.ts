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
