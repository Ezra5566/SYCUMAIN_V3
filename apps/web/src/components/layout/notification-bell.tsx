"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Bell } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth-context";
import { notificationApi } from "@/lib/platform-api";
import { Button } from "@/components/ui/button";

/** How often the badge refreshes while a page is open. */
const POLL_INTERVAL_MS = 60_000;

/** Same-tab signal that read state changed; the badge refreshes immediately. */
export const NOTIFICATIONS_CHANGED = "notifications:changed";

/**
 * Unread-notification indicator for the application header.
 *
 * The count is decorative: it is fetched from the API, never cached in local
 * storage, and a failure collapses to "no badge" rather than breaking the
 * header. Opening the notifications page is what actually reads the records.
 */
export function NotificationBell() {
  const t = useTranslations("notifications");
  const { hasPermission } = useAuth();
  const [unread, setUnread] = useState(0);
  const allowed = hasPermission("notifications.view");

  useEffect(() => {
    if (!allowed) return;
    let active = true;

    const load = async () => {
      try {
        const { unread_count } = await notificationApi.unreadCount();
        if (active) setUnread(unread_count);
      } catch {
        // A transient failure must not surface as a broken header.
        if (active) setUnread(0);
      }
    };

    // The notifications page mutates read state without a navigation. Without
    // this signal the badge would keep the pre-mutation count until the next
    // poll, contradicting the list the user is looking at.
    const onChanged = () => void load();
    window.addEventListener(NOTIFICATIONS_CHANGED, onChanged);

    void load();
    const timer = setInterval(load, POLL_INTERVAL_MS);
    return () => {
      active = false;
      clearInterval(timer);
      window.removeEventListener(NOTIFICATIONS_CHANGED, onChanged);
    };
  }, [allowed]);

  if (!allowed) return null;

  const label =
    unread > 0 ? t("unreadCount", { count: unread }) : t("title");

  return (
    <Button
      asChild
      variant="ghost"
      size="icon"
      className="scu-icon relative shrink-0"
      aria-label={label}
      title={label}
    >
      <Link href="/app/notifications">
        <Bell className="h-5 w-5" aria-hidden="true" />
        {unread > 0 && (
          <span
            className="motion-badge absolute -end-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold tabular-nums text-destructive-foreground"
            aria-hidden="true"
          >
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </Link>
    </Button>
  );
}
