"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { announcementApi } from "@/lib/platform-api";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { useErrorMessage } from "@/lib/use-error-message";
import { locales, localeLabels, type Locale } from "@/i18n/routing";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { FilterSelect } from "@/components/ui/filter-select";
import { ErrorState } from "@/components/ui/error-state";
import { toast } from "@/components/ui/toast";
import type {
  AnnouncementAudienceType,
  AnnouncementPriority,
} from "@/types/platform";

const PRIORITIES: AnnouncementPriority[] = ["LOW", "NORMAL", "HIGH", "URGENT"];

/** Mirrors AnnouncementAudienceType; MAJOR/PROGRAM/CLASS need a target id. */
const AUDIENCES: AnnouncementAudienceType[] = [
  "ALL",
  "STUDENTS",
  "TEACHERS",
  "STAFF",
];

interface TranslationDraft {
  title: string;
  body: string;
}

interface ComposeAnnouncementDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void;
}

const EMPTY: TranslationDraft = { title: "", body: "" };

/**
 * Create an announcement in one or more languages.
 *
 * The author's own language is the default locale and is required; the others
 * are optional and simply omitted from the payload when blank, so a missing
 * translation falls back to the original rather than being stored as empty text.
 */
export function ComposeAnnouncementDialog({
  open,
  onOpenChange,
  onCreated,
}: ComposeAnnouncementDialogProps) {
  const t = useTranslations("announcements");
  const tCommon = useTranslations("common");
  const locale = useLocale() as Locale;
  const localizeError = useErrorMessage();

  const [drafts, setDrafts] = useState<Record<string, TranslationDraft>>({});
  const [priority, setPriority] = useState<AnnouncementPriority>("NORMAL");
  const [audience, setAudience] = useState<AnnouncementAudienceType>("ALL");
  const [publishNow, setPublishNow] = useState(true);
  const [expanded, setExpanded] = useState<string[]>([locale]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<NormalizedError | null>(null);

  const draftFor = (target: string): TranslationDraft => drafts[target] ?? EMPTY;

  const setDraft = (target: string, patch: Partial<TranslationDraft>) =>
    setDrafts((current) => ({
      ...current,
      [target]: { ...draftFor(target), ...patch },
    }));

  const toggle = (target: string) =>
    setExpanded((current) =>
      current.includes(target)
        ? current.filter((item) => item !== target)
        : [...current, target],
    );

  const primary = draftFor(locale);
  const canSubmit =
    primary.title.trim().length > 0 && primary.body.trim().length > 0 && !saving;

  const handleSubmit = async () => {
    setSaving(true);
    setError(null);
    try {
      const translations = locales
        .map((target) => ({
          locale: target,
          title: draftFor(target).title.trim(),
          body: draftFor(target).body.trim(),
        }))
        .filter((entry) => entry.title && entry.body);

      const created = await announcementApi.create({
        default_locale: locale,
        is_pinned: false,
        priority,
        audience_type: audience,
        translations,
      });

      if (publishNow) {
        await announcementApi.publish(created.id);
        toast.success(t("publishSucceeded"));
      } else {
        toast.success(t("createdSucceeded"));
      }

      setDrafts({});
      setExpanded([locale]);
      onCreated();
    } catch (err) {
      setError(normalizeApiError(err, "create announcement"));
    } finally {
      setSaving(false);
    }
  };

  const localized = localizeError(error);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("createTitle")}</DialogTitle>
          <DialogDescription>{t("translationNotice")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <FilterSelect
              label={t("priority")}
              value={priority}
              showLabel
              options={PRIORITIES.map((value) => ({
                value,
                label: t(`priorities.${value}`),
              }))}
              onChange={(value) => setPriority(value as AnnouncementPriority)}
            />
            <FilterSelect
              label={t("audience")}
              value={audience}
              showLabel
              options={AUDIENCES.map((value) => ({
                value,
                label: t(`audiences.${value}`),
              }))}
              onChange={(value) => setAudience(value as AnnouncementAudienceType)}
            />
          </div>

          <div className="space-y-2">
            <p className="text-sm font-medium">{t("translations")}</p>

            {locales.map((target) => {
              const isOpen = expanded.includes(target);
              const draft = draftFor(target);
              const isPrimary = target === locale;

              return (
                <div key={target} className="rounded-md border">
                  <button
                    type="button"
                    onClick={() => toggle(target)}
                    aria-expanded={isOpen}
                    className="flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-sm font-medium hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span className="flex items-center gap-2">
                      {localeLabels[target]}
                      {isPrimary && (
                        <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase text-muted-foreground">
                          {t("originalLanguage")}
                        </span>
                      )}
                    </span>
                    {draft.title && (
                      <span className="truncate text-xs text-muted-foreground">
                        {draft.title}
                      </span>
                    )}
                  </button>

                  {isOpen && (
                    <div className="space-y-3 border-t p-3">
                      <div className="space-y-1.5">
                        <label
                          htmlFor={`title-${target}`}
                          className="text-xs font-medium"
                        >
                          {t("fieldTitle")}
                        </label>
                        <Input
                          id={`title-${target}`}
                          value={draft.title}
                          onChange={(event) =>
                            setDraft(target, { title: event.target.value })
                          }
                          dir={target === "ar" ? "rtl" : undefined}
                          maxLength={255}
                        />
                      </div>
                      <div className="space-y-1.5">
                        <label
                          htmlFor={`body-${target}`}
                          className="text-xs font-medium"
                        >
                          {t("body")}
                        </label>
                        <Textarea
                          id={`body-${target}`}
                          value={draft.body}
                          onChange={(event) =>
                            setDraft(target, { body: event.target.value })
                          }
                          dir={target === "ar" ? "rtl" : undefined}
                        />
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={publishNow}
              onChange={(event) => setPublishNow(event.target.checked)}
              className="h-4 w-4 rounded border-input"
            />
            {t("publishNow")}
          </label>

          {error && (
            <ErrorState title={localized.message} hint={localized.hint} />
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {tCommon("actions.cancel")}
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit}>
            {saving ? tCommon("states.saving") : tCommon("actions.create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
