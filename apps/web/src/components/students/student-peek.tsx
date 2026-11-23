"use client";

import { useFormatter, useTranslations } from "next-intl";
import { ArrowUpRight, Mail, MapPin, GraduationCap } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { StatusBadge, toneForStatus } from "@/components/ui/status-badge";
import type { StudentBrief } from "@/types/student";

/**
 * Quick view for one student.
 *
 * The directory is a scanning surface: most visits only need "who is this, are
 * they active, how do I reach them". Sending that to a full record page costs a
 * navigation, a history entry and a load. This dialog answers it in place and
 * keeps "Open full record" for the cases that actually need the record.
 */
export function StudentPeekDialog({
  student,
  open,
  onOpenChange,
}: {
  student: StudentBrief | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("students.peek");
  const tStatus = useTranslations("students.status");
  const tCommon = useTranslations("common");
  const format = useFormatter();

  if (!student) return null;

  const fullName = [student.first_name, student.last_name].filter(Boolean).join(" ");
  const initials = `${student.first_name[0] ?? ""}${student.last_name[0] ?? ""}`.toUpperCase();

  const rows = [
    {
      icon: GraduationCap,
      label: t("studentNumber"),
      value: <span className="font-mono">{student.student_id}</span>,
    },
    {
      icon: MapPin,
      label: t("nationality"),
      value: student.nationality ?? t("notProvided"),
    },
    {
      icon: Mail,
      label: t("email"),
      value: student.user_email ? (
        <span dir="ltr" className="break-all">{student.user_email}</span>
      ) : (
        t("notProvided")
      ),
    },
  ];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-base">{t("title")}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("description")}
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-start gap-3">
          <span
            className="scu-avatar h-14 w-14 shrink-0 text-base ring-1 ring-border ring-offset-2 ring-offset-background"
            data-tone={1}
            aria-hidden="true"
          >
            {initials}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-lg font-semibold tracking-[-0.02em]">
              {fullName}
            </p>
            {student.preferred_name && (
              <p className="truncate text-xs text-muted-foreground">
                ({student.preferred_name})
              </p>
            )}
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <StatusBadge tone={toneForStatus(student.status)}>
                {tStatus(student.status)}
              </StatusBadge>
              <span className="text-xs text-muted-foreground">
                {t("since", {
                  date: format.dateTime(new Date(student.created_at), { dateStyle: "medium" }),
                })}
              </span>
            </div>
          </div>
        </div>

        <dl className="grid gap-2 rounded-xl border border-border/70 bg-card/40 p-3">
          {rows.map((row) => (
            <div key={row.label} className="flex items-start gap-2.5">
              <row.icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <dt className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  {row.label}
                </dt>
                <dd className="truncate text-sm">{row.value}</dd>
              </div>
            </div>
          ))}
        </dl>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {tCommon("actions.close")}
          </Button>
          <Button asChild>
            <Link href={`/app/students/${student.id}`}>
              {t("openRecord")}
              <ArrowUpRight className="ms-1.5 h-4 w-4 rtl:-scale-x-100" aria-hidden="true" />
            </Link>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
