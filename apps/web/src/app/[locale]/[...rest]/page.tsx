import { notFound } from "next/navigation";

/**
 * Unknown paths inside a locale match this catch-all so the nearest
 * `not-found.tsx` renders with translations and the correct text direction.
 * Without it, unmatched URLs fall through to Next's unlocalized root 404.
 */
export default function LocalizedCatchAllPage() {
  notFound();
}
