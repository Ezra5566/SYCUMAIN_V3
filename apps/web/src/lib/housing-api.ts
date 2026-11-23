import { apiFetch } from "./api";
import type {
  BuildingBrief,
  BuildingDetail,
  HousingOverviewResponse,
  RoomDetail,
  RoomBrief,
  StudentHousingResponse,
  HousingAssignmentResponse,
} from "@/types/housing";

/** Rooms are owned by the API, so status values are the backend's. */
export type RoomStatus = "AVAILABLE" | "OUT_OF_SERVICE" | "RESERVED";

export async function getBuildings(): Promise<BuildingBrief[]> {
  return apiFetch("/api/v1/housing/buildings");
}

export async function getBuilding(
  buildingId: string
): Promise<BuildingDetail> {
  return apiFetch(`/api/v1/housing/buildings/${buildingId}`);
}

export async function getHousingOverview(): Promise<HousingOverviewResponse> {
  return apiFetch("/api/v1/housing/overview");
}

export async function getRoom(roomId: string): Promise<RoomDetail> {
  return apiFetch(`/api/v1/housing/rooms/${roomId}`);
}

/** Full occupant history, including ended assignments. */
export async function getRoomHistory(
  roomId: string
): Promise<HousingAssignmentResponse[]> {
  return apiFetch(`/api/v1/housing/rooms/${roomId}/history`);
}

export async function getBedHistory(
  bedId: string
): Promise<HousingAssignmentResponse[]> {
  return apiFetch(`/api/v1/housing/beds/${bedId}/history`);
}

export async function getFloorRooms(floorId: string): Promise<RoomBrief[]> {
  return apiFetch(`/api/v1/housing/floors/${floorId}/rooms`);
}

export async function getStudentHousing(
  studentId: string
): Promise<StudentHousingResponse> {
  return apiFetch(`/api/v1/housing/students/${studentId}/housing`);
}

export async function createAssignment(data: {
  student_id: string;
  bed_id: string;
  start_date: string;
  notes?: string;
}): Promise<HousingAssignmentResponse> {
  return apiFetch("/api/v1/housing/assignments", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function transferStudent(
  assignmentId: string,
  data: {
    new_bed_id: string;
    // The API calls this `transfer_date`; sending `start_date` is a 422.
    transfer_date: string;
    notes?: string;
  }
): Promise<HousingAssignmentResponse> {
  return apiFetch(`/api/v1/housing/assignments/${assignmentId}/transfer`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

/** End an active assignment, preserving it as history. */
export async function endAssignment(
  assignmentId: string
): Promise<HousingAssignmentResponse> {
  return apiFetch(`/api/v1/housing/assignments/${assignmentId}/end`, {
    method: "POST",
  });
}

// --- Structure administration ---
//
// Buildings, floors, rooms and beds were seed-only before Stage 8B. These calls
// are what the management UI uses to change the estate.

export async function createBuilding(data: {
  name: string;
  description?: string;
}): Promise<BuildingDetail> {
  return apiFetch("/api/v1/housing/buildings", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function createFloor(
  buildingId: string,
  floorNumber: number
): Promise<BuildingDetail> {
  return apiFetch(`/api/v1/housing/buildings/${buildingId}/floors`, {
    method: "POST",
    body: JSON.stringify({ floor_number: floorNumber }),
  });
}

export async function createRoom(
  floorId: string,
  data: { room_number: string; capacity: number }
): Promise<RoomDetail> {
  return apiFetch(`/api/v1/housing/floors/${floorId}/rooms`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateRoom(
  roomId: string,
  data: {
    room_number?: string;
    capacity?: number;
    status?: RoomStatus;
    is_active?: boolean;
  }
): Promise<RoomDetail> {
  return apiFetch(`/api/v1/housing/rooms/${roomId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function createBed(
  roomId: string,
  data: { label?: string; bed_number?: number } = {}
): Promise<RoomDetail> {
  return apiFetch(`/api/v1/housing/rooms/${roomId}/beds`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateBed(
  bedId: string,
  data: { label?: string | null; is_active?: boolean }
): Promise<RoomDetail> {
  return apiFetch(`/api/v1/housing/beds/${bedId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}
