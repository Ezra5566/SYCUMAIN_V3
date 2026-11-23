"use client";

import { useId, useState } from "react";
import { Plus, Pencil } from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/toast";

/**
 * A single reusable create/edit dialog for the academic structure.
 *
 * Majors, programmes, courses, periods, classrooms and class sections all have
 * the same interaction — open, fill four or five fields, save, refresh — so they
 * share one dialog driven by a field list instead of six near-identical
 * components that drift apart. The housing module keeps its own dialogs because
 * its create and edit paths genuinely differ (capacity derives from beds, room
 * status has operational meaning); nothing here does.
 *
 * Labels arrive already translated as strings rather than as keys: the callers
 * genuinely compose them from more than one namespace ("Add" from `common`,
 * "major" from `academics`), and a component that resolved keys itself would
 * have to guess which namespace each one lives in.
 *
 * Validation is deliberately shallow. The API is the boundary: it owns
 * uniqueness, referential integrity and the class/period date rules, and it
 * returns a stable error code this dialog renders in the user's language. A
 * second, weaker copy of those rules in the browser would only disagree with it.
 */

export type FieldType = "text" | "number" | "textarea" | "date" | "time" | "select";

export interface FieldSpec {
  /** Key sent to the API. */
  name: string;
  /** Already-translated label. */
  label: string;
  type: FieldType;
  required?: boolean;
  placeholder?: string;
  help?: string;
  min?: number;
  max?: number;
  /** For `select`. Values are API enum members or entity ids. */
  options?: { value: string; label: string }[];
  /** Render the control full-width (textarea, or a long select list). */
  full?: boolean;
  /**
   * Blank means "clear this field" and is sent as JSON `null`.
   *
   * Without it a blank input is omitted from the payload, which is right for a
   * required-once field (a code, a period id) but wrong for an optional one:
   * omitting `description` leaves the old text in place, so the user watches
   * the field they just emptied stay empty on screen and stay set in the
   * database.
   */
  nullable?: boolean;
}

export type FieldValues = Record<string, string>;

/**
 * Turn raw form strings into an API payload.
 *
 * Blank values are omitted unless the field is `nullable`, in which case they
 * become `null`. Numbers are coerced only when the field declares itself
 * numeric — sending "" for a UUID would be a 422, and sending "3" for an
 * integer is a 422 too.
 */
export function toPayload(
  fields: FieldSpec[],
  values: FieldValues,
): Record<string, string | number | null> {
  const payload: Record<string, string | number | null> = {};

  for (const field of fields) {
    const raw = (values[field.name] ?? "").trim();
    if (raw === "") {
      if (field.nullable) payload[field.name] = null;
      continue;
    }
    payload[field.name] = field.type === "number" ? Number(raw) : raw;
  }

  return payload;
}

export interface EntityFormDialogProps {
  title: string;
  description: string;
  submitLabel: string;
  /** Toast shown after a successful save. */
  successMessage: string;
  fields: FieldSpec[];
  /** Present for edit; omitted for create. */
  initial?: FieldValues;
  /** Distinguishes create (plus icon, primary) from edit (pencil, outline). */
  mode: "create" | "edit";
  /** Create mode only: the visible trigger label. */
  triggerLabel?: string;
  onSubmit: (values: FieldValues) => Promise<unknown>;
  onSaved: () => Promise<void> | void;
  /** Labels for the trigger and the footer buttons. */
  cancelLabel: string;
  savingLabel: string;
  variant?: "default" | "outline" | "ghost";
  size?: "default" | "sm" | "icon";
}

export function EntityFormDialog({
  title,
  description,
  submitLabel,
  successMessage,
  fields,
  initial,
  mode,
  triggerLabel,
  onSubmit,
  onSaved,
  cancelLabel,
  savingLabel,
  variant,
  size,
}: EntityFormDialogProps) {
  const localizeError = useErrorMessage();

  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);
  const [values, setValues] = useState<FieldValues>(initial ?? {});

  function change(name: string, value: string) {
    setValues((current) => ({ ...current, [name]: value }));
  }

  function openWith() {
    // Reset to the record's current state each time: after a failed save the
    // dialog stays open, and a later "edit" must not inherit those edits.
    setValues(initial ?? {});
    setFailure(null);
    setOpen(true);
  }

  const missingRequired = fields.some(
    (field) => field.required && (values[field.name] ?? "").trim() === "",
  );

  async function submit() {
    setBusy(true);
    setFailure(null);
    try {
      await onSubmit(values);
      toast.success(successMessage);
      await onSaved();
      setOpen(false);
    } catch (error) {
      setFailure(normalizeApiError(error, "academic"));
    } finally {
      setBusy(false);
    }
  }

  const trigger =
    mode === "create" ? (
      <Button variant={variant ?? "default"} size={size ?? "default"} onClick={openWith}>
        <Plus className="me-1 h-4 w-4" aria-hidden="true" />
        {triggerLabel ?? title}
      </Button>
    ) : (
      <Button
        variant={variant ?? "ghost"}
        size={size ?? "icon"}
        onClick={openWith}
        aria-label={title}
        title={title}
      >
        <Pencil className="h-4 w-4" aria-hidden="true" />
      </Button>
    );

  return (
    <>
      {trigger}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-2 sm:grid-cols-2">
            {fields.map((field) => (
              <Field
                key={field.name}
                field={field}
                value={values[field.name] ?? ""}
                onChange={(value) => change(field.name, value)}
              />
            ))}
          </div>

          {failure && (
            <p role="alert" className="text-sm text-destructive">
              {localizeError(failure).message}
            </p>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              {cancelLabel}
            </Button>
            <Button onClick={() => void submit()} disabled={busy || missingRequired}>
              {busy ? savingLabel : submitLabel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function Field({
  field,
  value,
  onChange,
}: {
  field: FieldSpec;
  value: string;
  onChange: (value: string) => void;
}) {
  const id = useId();

  return (
    <div className={field.full ? "space-y-2 sm:col-span-2" : "space-y-2"}>
      <label htmlFor={id} className="text-sm font-medium">
        {field.label}
        {field.required && (
          <span className="ms-1 text-destructive" aria-hidden="true">
            *
          </span>
        )}
      </label>

      {field.type === "textarea" ? (
        <Textarea
          id={id}
          value={value}
          rows={3}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : field.type === "select" ? (
        <select
          id={id}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="h-10 w-full cursor-pointer rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {(field.options ?? []).map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      ) : (
        <Input
          id={id}
          type={field.type}
          value={value}
          min={field.min}
          max={field.max}
          placeholder={field.placeholder}
          onChange={(event) => onChange(event.target.value)}
        />
      )}

      {field.help && <p className="text-xs text-muted-foreground">{field.help}</p>}
    </div>
  );
}
