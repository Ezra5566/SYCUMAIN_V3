import createMiddleware from "next-intl/middleware";
import { routing } from "@/i18n/routing";

/**
 * Locale negotiation.
 *
 * Precedence, highest first:
 *   1. An explicit locale prefix in the URL (`/zh/app/students`).
 *   2. The `NEXT_LOCALE` cookie set by the language switcher.
 *   3. The browser's `Accept-Language` header.
 *   4. The default locale.
 *
 * Only page routes are localized. Server-side redirects to the API are
 * unaffected because the matcher excludes everything that is not a page.
 */
export default createMiddleware(routing);

export const config = {
  // Skip Next.js internals, the API, and any request for a static file.
  matcher: ["/((?!api|_next|_vercel|.*\\..*).*)"],
};
