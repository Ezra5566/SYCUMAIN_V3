import { apiFetch } from "@/lib/api";
import type {
  Placement,
  PlacementInput,
  PlacementListResponse,
} from "@/types/placement";

class PlacementApiClient {
  async list(studentId: string): Promise<PlacementListResponse> {
    return apiFetch<PlacementListResponse>(
      `/api/v1/students/${studentId}/placements`,
    );
  }

  async create(studentId: string, input: PlacementInput): Promise<Placement> {
    return apiFetch<Placement>(`/api/v1/students/${studentId}/placements`, {
      method: "POST",
      body: JSON.stringify(input),
    });
  }
}

export const placementApi = new PlacementApiClient();
