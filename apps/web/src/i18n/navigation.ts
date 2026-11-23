import { createNavigation } from "next-intl/navigation";
import { routing } from "./routing";

/**
 * Locale-aware navigation primitives.
 *
 * Application code MUST import `Link`, `useRouter`, `usePathname` and
 * `redirect` from here rather than from `next/link` / `next/navigation`.
 * These wrappers preserve the active locale automatically, which is what keeps
 * a user in Chinese when they click from the dashboard into the student
 * directory.
 */
export const { Link, redirect, usePathname, useRouter, getPathname } =
  createNavigation(routing);
