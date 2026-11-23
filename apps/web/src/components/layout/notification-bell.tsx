"use client";

import { useCallback, useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { ArrowRight, Bell, CheckCheck } from "lucide-react";
import { Link, useRouter } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth-context";
import { notificationApi } from "@/lib/platform-api";
import { notificationMessageKey } from "@/lib/notification-types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { PortalNotification } from "@/types/platform";

/** How often the badge refreshes while a page is open. */
const POLL_INTERVAL_MS = 60_000;
const PEEK_SIZE = 6;

/** Same-tab signal that read state changed; the badge refreshes immediately. */
export const NOTIFICATIONS_CHANGED = "notifications:changed";

/**
 * Unread indicator plus an in-header peek at the latest records.
 *
 * Clicking the bell used to be a navigation to /app/notifications just to find
 * out whether anything needed attention. The popover answers that in place and
 * keeps the full page for triage. The list is fetched only when the panel
 * opens, so a closed popover costs one unread-count request per minute, not a
 * list request.
 */
export function NotificationBell() {
  const t = useTranslations("notifications");
  const tCommon = useTranslations("common");
  const format = useFormatter();
  const router = useRouter();
  const { hasPermission } = useAuth();

  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<PortalNotification[]>([]);
  const [loading, setLoading] = useState(false);
  const [working, setWorking] = useState(false);
  const allowed = hasPermission("notifications.view");

  const loadCount = useCallback(async () => {
    try {
      const { unread_count } = await notificationApi.unreadCount();
      setUnread(unread_count);
    } catch {
      // A transient failure must not surface as a broken header.
      setUnread(0);
    }
  }, []);

  useEffect(() => {
    if (!allowed) return;
    let active = true;
    const load = async () => {
      try {
        const { unread_count } = await notificationApi.unreadCount();
        if (active) setUnread(unread_count);
      } catch {
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

  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true);
    notificationApi
      .list({ page_size: PEEK_SIZE })
      .then((response) => {
        if (active) setItems(response.items);
      })
      .catch(() => {
        if (active) setItems([]);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [open]);

  if (!allowed) return null;

  const markAll = async () => {
    setWorking(true);
    try {
      await notificationApi.markAllRead();
      setUnread(0);
      setItems((current) => current.map((item) => ({ ...item, read_at: item.read_at ?? new Date().toISOString() })));
      window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED));
    } finally {
      setWorking(false);
    }
  };

  const openItem = async (item: PortalNotification) => {
    setOpen(false);
    if (!item.read_at) {
      // Optimistic: the badge drops immediately, the request is not awaited so
      // the click still feels like a navigation.
      setUnread((count) => Math.max(0, count - 1));
      notificationApi
        .markRead(item.id)
        .then(() => window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED)))
        .catch(() => void loadCount());
    }
    if (item.link_url) router.push(item.link_url);
    else router.push("/app/notifications");
  };

  const label = unread > 0 ? t("unreadCount", { count: unread }) : t("title");

  return (
    <DropdownMenu.Root open={open} onOpenChange={setOpen}>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className="scu-icon relative shrink-0"
          aria-label={label}
          title={label}
        >
          <Bell className="h-5 w-5" aria-hidden="true" />
          {unread > 0 && (
            <span
              className="motion-badge absolute -end-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold tabular-nums text-destructive-foreground"
              aria-hidden="true"
            >
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={10}
          collisionPadding={12}
          className="scu-pop w-[min(23rem,calc(100vw-1.5rem))] p-0"
        >
          <div className="flex items-center justify-between gap-2 border-b border-border/70 px-3 py-2.5">
            <div>
              <p className="text-[13px] font-semibold">{t("title")}</p>
              <p className="text-[11px] text-muted-foreground">
                {unread > 0 ? t("unreadCount", { count: unread }) : t("allMarkedRead")}
              </p>
            </div>
            {unread > 0 && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-[11px]"
                onClick={() => void markAll()}
                disabled={working}
              >
                <CheckCheck className="me-1 h-3.5 w-3.5" aria-hidden="true" />
                {t("markAllRead")}
              </Button>
            )}
          </div>

          <div className="max-h-[min(22rem,55vh)] overflow-y-auto p-1.5">
            {loading ? (
              <div className="space-y-2 p-2" aria-busy="true">
                <div className="scu-skeleton h-9 w-full" />
                <div className="scu-skeleton h-9 w-full" />
                <div className="scu-skeleton h-9 w-full" />
              </div>
            ) : items.length === 0 ? (
              <p className="px-3 py-8 text-center text-xs text-muted-foreground">
                {t("empty")}
              </p>
            ) : (
              <ul className="space-y-0.5">
                {items.map((item) => {
                  const unreadItem = !item.read_at;
                  const messageKey = notificationMessageKey(item.type);
                  return (
                    <li key={item.id}>
                      <button
                        type="button"
                        onClick={() => void openItem(item)}
                        className={cn(
                          "flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-start transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          unreadItem && "bg-primary/[0.06]",
                        )}
                      >
                        <span
                          className={cn(
                            "mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full",
                            unreadItem ? "bg-primary" : "bg-transparent",
                          )}
                          aria-hidden="true"
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[12.5px] font-semibold">
                            {t(`types.${item.type}`)}
                          </span>
                          {messageKey && (
                            <span className="mt-0.5 block text-[11.5px] leading-snug text-muted-foreground">
                              {t(`messages.${messageKey}`)}
                            </span>
                          )}
                          <span className="mt-0.5 block text-[10.5px] text-muted-foreground/80">
                            {format.dateTime(new Date(item.created_at), {
                              dateStyle: "medium",
                              timeStyle: "short",
                            })}
                          </span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <div className="border-t border-border/70 p-1.5">
            <Link
              href="/app/notifications"
              className="scu-pop__item justify-between"
              onClick={() => setOpen(false)}
            >
              <span>{tCommon("labels.viewAll")}</span>
              <ArrowRight className="h-3.5 w-3.5 rtl:-scale-x-100" aria-hidden="true" />
            </Link>
          </div>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
