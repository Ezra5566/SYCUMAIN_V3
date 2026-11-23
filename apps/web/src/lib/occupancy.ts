/**
 * Occupancy presentation.
 *
 * Colour is a *reinforcement*, never the message. Every surface defined here is
 * always rendered alongside a status label and an occupancy count, and every
 * room carries an accessible label describing its state in words. That keeps
 * the dormitory view usable for colour-blind users and in high-contrast mode.
 *
 * All states resolve through semantic tokens so the same room reads correctly
 * in light and dark appearance rather than relying on a pale fill designed only
 * for a white surface.
 */

/** Border/background treatment for a room tile, keyed by occupancy status. */
export function roomSurface(status: string): string {
  switch (status) {
    case "AVAILABLE":
      return "border-success/30 bg-success-soft hover:bg-success-soft/75";
    case "PARTIAL":
      return "border-warning/35 bg-warning-soft hover:bg-warning-soft/75";
    case "FULL":
      return "border-destructive/30 bg-destructive/10 hover:bg-destructive/15";
    case "RESERVED":
      return "border-info/30 bg-info-soft hover:bg-info-soft/75";
    case "OUT_OF_SERVICE":
      return "border-border bg-muted opacity-70 hover:opacity-100";
    default:
      return "border-border bg-background";
  }
}

/** The dot colour used in the legend, matching `roomSurface`. */
export function occupancyDot(status: string): string {
  switch (status) {
    case "AVAILABLE":
      return "bg-success";
    case "PARTIAL":
      return "bg-warning";
    case "FULL":
      return "bg-destructive";
    case "RESERVED":
      return "bg-info";
    case "OUT_OF_SERVICE":
      return "bg-muted-foreground/40";
    default:
      return "bg-muted-foreground/40";
  }
}

/** Occupancy statuses in the order the legend lists them. */
export const OCCUPANCY_ORDER = [
  "AVAILABLE",
  "PARTIAL",
  "FULL",
  "RESERVED",
  "OUT_OF_SERVICE",
] as const;

export function occupancyPercent(occupied: number, capacity: number): number {
  if (capacity <= 0 || occupied <= 0) return 0;
  // A room with any occupant is never "0% occupied" in the interface: that
  // reads as empty and hides a real assignment on a large-capacity room.
  return Math.max(1, Math.round((occupied / capacity) * 100));
}
