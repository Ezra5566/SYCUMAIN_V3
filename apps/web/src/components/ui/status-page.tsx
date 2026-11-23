"use client";

import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { Compass } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { ScuMark } from "@/components/brand/scu-mark";
import { cn } from "@/lib/utils";

interface StatusPageProps {
  title: string;
  description: string;
  icon?: LucideIcon;
  /** Primary recovery action. */
  primaryAction?: {
    label: string;
    href: string;
  };
  /** Secondary safe destination, normally the dashboard or support. */
  secondaryAction?: {
    label: string;
    href: string;
  };
  children?: ReactNode;
  className?: string;
}

/**
 * A safe, localized explanation for an application-level state.
 *
 * It intentionally renders no error message, stack, request id, token or
 * internal route detail. Authentication remains with the server and the normal
 * AuthGuard; this surface is only a navigation/recovery affordance.
 */
export function StatusPage({
  title,
  description,
  icon: Icon = Compass,
  primaryAction,
  secondaryAction,
  children,
  className,
}: StatusPageProps) {
  return (
    <main
      className={cn(
        "flex min-h-screen items-center justify-center bg-background px-4 py-10",
        className,
      )}
    >
      <div className="w-full max-w-md text-center">
        <div className="mx-auto mb-6 flex h-12 w-12 items-center justify-center rounded-full bg-[#f7f4ec] shadow-card ring-1 ring-black/10">
          <ScuMark className="h-9 w-9" />
        </div>
        <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <Icon className="h-5 w-5" aria-hidden="true" />
        </span>
        <h1 className="mt-4 text-xl font-semibold tracking-[-0.02em]">{title}</h1>
        <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-muted-foreground">
          {description}
        </p>
        {(primaryAction || secondaryAction) && (
          <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
            {primaryAction && (
              <Link
                href={primaryAction.href}
                className="inline-flex h-10 items-center justify-center rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70 focus-visible:ring-offset-2"
              >
                {primaryAction.label}
              </Link>
            )}
            {secondaryAction && (
              <Link
                href={secondaryAction.href}
                className="inline-flex h-10 items-center justify-center rounded-lg border border-border bg-card px-4 text-sm font-medium text-foreground shadow-sm transition-colors hover:border-primary/30 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70 focus-visible:ring-offset-2"
              >
                {secondaryAction.label}
              </Link>
            )}
          </div>
        )}
        {children}
      </div>
    </main>
  );
}
