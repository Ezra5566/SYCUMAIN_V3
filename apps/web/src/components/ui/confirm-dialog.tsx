"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/**
 * Confirmation dialog for destructive or otherwise irreversible actions.
 *
 * The confirm button carries the action's own verb ("Remove", "Archive",
 * "Approve") rather than a generic "OK": a dialog that says "Delete 201-A?"
 * above a button labelled "OK" makes the user translate intent into assent,
 * which is precisely the moment a mis-click becomes irreversible.
 *
 * A failure is reported inside the dialog and leaves it open, so the user can
 * retry or cancel without losing what they were doing.
 */

interface ConfirmDialogProps {
  title: string;
  description: string;
  /** The action verb on the confirming button, e.g. "Remove". */
  confirmLabel: string;
  /** Optional extra input, e.g. a rejection reason. */
  children?: React.ReactNode;
  onConfirm: () => Promise<unknown>;
  onDone?: () => Promise<void> | void;
  /** Renders the trigger as an icon-only button with this accessible label. */
  triggerLabel?: string;
  triggerIcon?: React.ReactNode;
  variant?: "default" | "outline" | "ghost" | "destructive";
  size?: "default" | "sm" | "icon";
  disabled?: boolean;
  /** Blocks confirmation until the caller's condition is met. */
  confirmDisabled?: boolean;
}

export function ConfirmDialog({
  title,
  description,
  confirmLabel,
  children,
  onConfirm,
  onDone,
  triggerLabel,
  triggerIcon,
  variant = "outline",
  size = "sm",
  disabled,
  confirmDisabled,
}: ConfirmDialogProps) {
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);

  async function confirm() {
    setBusy(true);
    setFailure(null);
    try {
      await onConfirm();
      await onDone?.();
      setOpen(false);
    } catch (error) {
      setFailure(normalizeApiError(error, "generic"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button
        variant={variant}
        size={size}
        onClick={() => {
          setFailure(null);
          setOpen(true);
        }}
        disabled={disabled}
        aria-label={triggerLabel}
        title={triggerLabel}
      >
        {triggerIcon}
        {size !== "icon" && (triggerLabel ?? confirmLabel)}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>

          {children && <div className="py-2">{children}</div>}

          {failure && (
            <p role="alert" className="text-sm text-destructive">
              {localizeError(failure).message}
            </p>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              {tCommon("actions.cancel")}
            </Button>
            <Button
              variant={variant === "destructive" ? "destructive" : "default"}
              onClick={() => void confirm()}
              disabled={busy || confirmDisabled}
            >
              {busy ? tCommon("states.saving") : confirmLabel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
