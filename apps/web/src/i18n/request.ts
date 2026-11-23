import { hasLocale } from "next-intl";
import { getRequestConfig } from "next-intl/server";
import { defaultLocale, routing } from "./routing";

/**
 * Server-side message loading.
 *
 * Messages are imported statically so the bundler can tree-shake and so there
 * is no filesystem read at request time. A missing locale falls back to the
 * default locale rather than throwing, so a stale cookie or hand-edited URL
 * degrades to English instead of breaking the page.
 */
export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = hasLocale(routing.locales, requested) ? requested : defaultLocale;

  return {
    locale,
    messages: (await import(`../../messages/${locale}.json`)).default,
    // Document expiry windows and other date-sensitive screens must not shift
    // with the server's timezone.
    timeZone: "Asia/Shanghai",
    // A missing key is a bug, but it must never blank a page for a student.
    // The key path is rendered instead, which is obvious in review and QA.
    onError(error) {
      if (process.env.NODE_ENV !== "production") {
        console.error(`[i18n] ${error.message}`);
      }
    },
    getMessageFallback({ namespace, key }) {
      return namespace ? `${namespace}.${key}` : key;
    },
  };
});
