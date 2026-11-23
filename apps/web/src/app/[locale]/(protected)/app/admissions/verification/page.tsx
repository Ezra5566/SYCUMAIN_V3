"use client";

import { useCallback, useMemo, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import {
  Check,
  ClipboardCheck,
  Eye,
  Pencil,
  Plus,
  ShieldAlert,
  SlidersHorizontal,
  Undo2,
  UserRoundCheck,
} from "lucide-react";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth-context";
import { AppShell } from "@/components/layout/app-shell";
import { admissionApi } from "@/lib/admission-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { SearchInput } from "@/components/ui/search-input";
import { FilterSelect } from "@/components/ui/filter-select";
import { DataTable, type Column } from "@/components/ui/data-table";
import { Pagination } from "@/components/ui/pagination";
import { EmptyState } from "@/components/ui/empty-state";
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "@/components/ui/toast";
import { MigrationCandidateDialog } from "@/components/admissions/migration-candidate-dialog";
import type {
  AdmissionVerificationStatus,
  ConfirmationInput,
  ConfirmationSlot,
  EvidenceType,
  MigrationQueueItem,
  MigrationQueueResponse,
  VerificationAct,
} from "@/types/admission";
import type { AdmissionForPlacement } from "@/types/placement";

const PAGE_SIZE = 25;
const STATUS_VALUES: AdmissionVerificationStatus[] = [
  "UNVERIFIED",
  "VERIFIED",
  "DISPUTED",
  "REVOKED",
];
const SLOT_VALUES: ConfirmationSlot[] = ["MANAGEMENT", "ADMIN"];
const EVIDENCE_VALUES: EvidenceType[] = [
  "ADMISSION_LETTER",
  "ENROLMENT_RECORD",
  "REGISTER_EXTRACT",
  "OTHER",
];

type ActionState =
  | { type: "confirm"; slot: ConfirmationSlot }
  | { type: "revoke"; slot: ConfirmationSlot }
  | { type: "correct" }
  | null;

function toneForTrust(status: AdmissionVerificationStatus): StatusTone {
  if (status === "VERIFIED") return "success";
  if (status === "DISPUTED") return "danger";
  if (status === "REVOKED") return "warning";
  return "neutral";
}

function toneForSlotState(state: string): StatusTone {
  if (state === "CONFIRMED") return "success";
  if (state === "REVOKED") return "warning";
  return "neutral";
}

function slotState(
  item: MigrationQueueItem,
  slot: ConfirmationSlot,
): string {
  return slot === "MANAGEMENT"
    ? item.management_confirmation_state
    : item.admin_confirmation_state;
}

function slotConfirmedBy(
  item: MigrationQueueItem,
  slot: ConfirmationSlot,
): string | null {
  return slot === "MANAGEMENT"
    ? item.management_confirmed_by_id
    : item.admin_confirmed_by_id;
}

function latestConfirm(
  acts: VerificationAct[],
  slot: ConfirmationSlot,
): VerificationAct | undefined {
  return [...acts]
    .reverse()
    .find((act) => act.slot === slot && act.action === "CONFIRM");
}

function TrustBadge({ status }: { status: AdmissionVerificationStatus }) {
  const t = useTranslations("admissionVerification");
  return (
    <StatusBadge tone={toneForTrust(status)}>
      {t(`status.${status}`)}
    </StatusBadge>
  );
}

function SlotPills({ item }: { item: MigrationQueueItem }) {
  const t = useTranslations("admissionVerification");
  return (
    <div className="flex flex-wrap gap-1.5">
      {SLOT_VALUES.map((slot) => {
        const state = slotState(item, slot);
        return (
          <Badge
            key={slot}
            variant="outline"
            className="gap-1 whitespace-nowrap px-2 py-0.5 text-[10px] font-semibold"
          >
            <span>{t(`slots.${slot}`)}</span>
            <span className={state === "CONFIRMED" ? "text-success" : "text-muted-foreground"}>
              {t(`slotState.${state}`)}
            </span>
          </Badge>
        );
      })}
    </div>
  );
}

export default function AdmissionVerificationPage() {
  const t = useTranslations("admissionVerification");
  const tCommon = useTranslations("common");
  const format = useFormatter();
  const { hasPermission, user } = useAuth();
  const localizeError = useErrorMessage();

  const [statusFilter, setStatusFilter] = useState<AdmissionVerificationStatus | "">(
    "UNVERIFIED",
  );
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [action, setAction] = useState<ActionState>(null);
  const [candidateEditor, setCandidateEditor] = useState<{
    candidate?: MigrationQueueItem;
  } | null>(null);

  const allowed = hasPermission("academic.view_admissions");
  const fetchQueue = useCallback(() => {
    if (!allowed) return Promise.resolve(null);
    return admissionApi.queue({
      verification_status: statusFilter || undefined,
      search: search.trim() || undefined,
      page,
      page_size: PAGE_SIZE,
    });
  }, [allowed, statusFilter, search, page]);
  const queue = useApi<MigrationQueueResponse | null>(
    fetchQueue,
    [allowed, statusFilter, search, page],
    "migration verification queue",
  );

  const selected =
    queue.data?.items.find((item) => item.admission_id === selectedId) ?? null;
  const selectedStudentId = selected?.student_id;
  const selectedAdmissionId = selected?.admission_id;
  const fetchActs = useCallback(
    () =>
      selectedStudentId && selectedAdmissionId
        ? admissionApi.acts(selectedStudentId, selectedAdmissionId)
        : Promise.resolve([]),
    [selectedStudentId, selectedAdmissionId],
  );
  const acts = useApi<VerificationAct[]>(
    fetchActs,
    [selectedStudentId, selectedAdmissionId],
    "migration verification acts",
  );
  const fetchStudentAdmissions = useCallback(
    () =>
      selectedStudentId
        ? admissionApi.admissions(selectedStudentId)
        : Promise.resolve([]),
    [selectedStudentId],
  );
  const studentAdmissions = useApi<AdmissionForPlacement[]>(
    fetchStudentAdmissions,
    [selectedStudentId],
    "student admission history",
  );

  const localizedError = localizeError(queue.error);
  const disabled = queue.error?.code === "MIGRATION_CONSOLE_DISABLED";
  const forbidden = !allowed || (queue.error?.kind === "forbidden" && !disabled);

  const canManagement = hasPermission("academic.confirm_admission_management");
  const canAdmin = hasPermission("academic.confirm_admission_admin");
  const canCorrect = hasPermission("academic.correct_original_admission");
  const canManageAdmissions = hasPermission("academic.manage_admissions");
  const canConfirm = (slot: ConfirmationSlot) =>
    slot === "MANAGEMENT" ? canManagement : canAdmin;
  const canRevoke = (slot: ConfirmationSlot) =>
    slot === "MANAGEMENT" ? canManagement : canAdmin;

  const statusOptions = useMemo(
    () => [
      { value: "", label: t("filters.all") },
      ...STATUS_VALUES.map((value) => ({
        value,
        label: t(`status.${value}`),
      })),
    ],
    [t],
  );

  const refreshAfterAction = () => {
    queue.refetch();
    acts.refetch();
  };

  const columns: Column<MigrationQueueItem>[] = [
    {
      key: "student",
      header: t("columns.student"),
      cell: (item) => (
        <div className="min-w-0">
          <Link
            href={`/app/students/${item.student_id}`}
            className="rounded-sm font-medium hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {item.student_name}
          </Link>
          <p className="font-mono text-xs text-muted-foreground" dir="ltr">
            {item.student_number}
          </p>
        </div>
      ),
    },
    {
      key: "intake",
      header: t("columns.intake"),
      hideOnMobile: true,
      cell: (item) => (
        <div className="min-w-0">
          <p className="text-sm">{item.admission_intake_name ?? "—"}</p>
          <p className="font-mono text-xs text-muted-foreground">
            {item.admission_intake_code ?? "—"}
          </p>
        </div>
      ),
    },
    {
      key: "program",
      header: t("columns.programme"),
      hideOnMobile: true,
      cell: (item) => (
        <div className="min-w-0">
          <p className="text-sm">{item.admitted_program_name ?? "—"}</p>
          <p className="truncate text-xs text-muted-foreground">
            {item.admitted_program_offering_name ?? "—"}
          </p>
        </div>
      ),
    },
    {
      key: "trust",
      header: t("columns.trust"),
      cell: (item) => <TrustBadge status={item.verification_status} />,
    },
    {
      key: "slots",
      header: t("columns.slots"),
      hideOnMobile: true,
      cell: (item) => <SlotPills item={item} />,
    },
    {
      key: "pointer",
      header: t("columns.pointer"),
      hideOnMobile: true,
      cell: (item) =>
        item.is_original_admission ? (
          <Badge variant="secondary" className="text-[10px]">
            {t("pointer.current")}
          </Badge>
        ) : item.original_admission_id ? (
          <span className="text-xs text-muted-foreground">{t("pointer.other")}</span>
        ) : (
          <span className="text-xs text-muted-foreground">{t("pointer.unset")}</span>
        ),
    },
    {
      key: "actions",
      header: tCommon("labels.actions"),
      className: "text-end",
      cell: (item) => (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setSelectedId(item.admission_id)}
        >
          <Eye className="h-3.5 w-3.5" aria-hidden="true" />
          {t("actions.review")}
        </Button>
      ),
    },
  ];

  return (
    <AppShell>
      <PageHeader
        title={t("title")}
        description={
          queue.data
            ? t("subtitleCount", { count: queue.data.total })
            : t("subtitle")
        }
        breadcrumbs={[
          { label: tCommon("labels.overview"), href: "/app" },
          { label: t("title") },
        ]}
        actions={
          allowed && !disabled && canManageAdmissions ? (
            <Button onClick={() => setCandidateEditor({})}>
              <Plus className="me-1 h-4 w-4" aria-hidden="true" />
              {t("candidate.add")}
            </Button>
          ) : undefined
        }
      />

      {forbidden ? (
        <EmptyState title={t("deniedTitle")} message={t("deniedMessage")} />
      ) : disabled ? (
        <EmptyState title={t("disabledTitle")} message={t("disabledMessage")} />
      ) : (
        <>
          <Card className="mb-4">
            <CardHeader className="flex-row items-center gap-2 space-y-0 pb-3">
              <SlidersHorizontal
                className="h-4 w-4 text-muted-foreground"
                aria-hidden="true"
              />
              <CardTitle className="text-sm">{tCommon("labels.filters")}</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <SearchInput
                value={search}
                onChange={(value) => {
                  setSearch(value);
                  setPage(1);
                }}
                placeholder={t("filters.searchPlaceholder")}
                className="sm:col-span-2 lg:col-span-1"
              />
              <FilterSelect
                label={t("filters.status")}
                value={statusFilter}
                showLabel
                options={statusOptions}
                onChange={(value) => {
                  setStatusFilter(value as AdmissionVerificationStatus | "");
                  setPage(1);
                }}
              />
              <div className="flex items-end">
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {t("filters.hint")}
                </p>
              </div>
            </CardContent>
          </Card>

          <DataTable
            columns={columns}
            rows={queue.data?.items ?? []}
            rowKey={(item) => item.admission_id}
            loading={queue.loading}
            error={queue.error ? localizedError.message : null}
            onRetry={queue.refetch}
            emptyTitle={t("emptyTitle")}
            emptyMessage={t("emptyMessage")}
            mobileCard={(item) => (
              <div className="space-y-2.5">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <Link
                      href={`/app/students/${item.student_id}`}
                      className="font-medium hover:text-primary hover:underline"
                    >
                      {item.student_name}
                    </Link>
                    <p className="font-mono text-xs text-muted-foreground" dir="ltr">
                      {item.student_number}
                    </p>
                  </div>
                  <TrustBadge status={item.verification_status} />
                </div>
                <p className="text-sm">
                  {item.admission_intake_name ?? "—"} ·{" "}
                  {item.admitted_program_name ?? "—"}
                </p>
                <SlotPills item={item} />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setSelectedId(item.admission_id)}
                >
                  <Eye className="h-3.5 w-3.5" aria-hidden="true" />
                  {t("actions.review")}
                </Button>
              </div>
            )}
          />

          {queue.data && (
            <Pagination
              page={queue.data.page}
              pageSize={queue.data.page_size}
              total={queue.data.total}
              totalPages={Math.max(
                1,
                Math.ceil(queue.data.total / queue.data.page_size),
              )}
              onPageChange={setPage}
            />
          )}
        </>
      )}

      <Dialog
        open={!!selected}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedId(null);
            setAction(null);
          }
        }}
      >
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
          {selected && (
            <>
              <DialogHeader>
                <DialogTitle>{selected.student_name}</DialogTitle>
                <DialogDescription>
                  {selected.student_number} ·{" "}
                  {selected.admission_intake_name ?? t("detail.unknownIntake")} ·{" "}
                  {selected.admitted_program_name ?? t("detail.unknownProgram")}
                </DialogDescription>
              </DialogHeader>

              <div className="flex flex-wrap items-center gap-2">
                <TrustBadge status={selected.verification_status} />
                {selected.is_original_admission ? (
                  <Badge variant="secondary">{t("pointer.current")}</Badge>
                ) : selected.original_admission_id ? (
                  <Badge variant="outline">{t("pointer.other")}</Badge>
                ) : (
                  <Badge variant="outline">{t("pointer.unset")}</Badge>
                )}
                {selected.verified_at && (
                  <span className="text-xs text-muted-foreground">
                    {t("detail.lastVerified", {
                      date: format.dateTime(new Date(selected.verified_at), {
                        dateStyle: "medium",
                        timeStyle: "short",
                      }),
                    })}
                  </span>
                )}
              </div>

              {selected.verification_status === "DISPUTED" && (
                <div
                  role="alert"
                  className="rounded-xl border border-destructive/25 bg-destructive/[0.05] p-4"
                >
                  <p className="flex items-center gap-2 text-sm font-semibold text-destructive">
                    <ShieldAlert className="h-4 w-4" aria-hidden="true" />
                    {t("detail.conflictTitle")}
                  </p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {t("detail.conflictBody")}
                  </p>
                  <ConflictSnapshots acts={acts.data ?? []} />
                </div>
              )}

              <div className="grid gap-3 sm:grid-cols-2">
                {SLOT_VALUES.map((slot) => (
                  <SlotCard
                    key={slot}
                    item={selected}
                    slot={slot}
                    acts={acts.data ?? []}
                    format={format}
                  />
                ))}
              </div>

              <div className="flex flex-wrap gap-2">
                {SLOT_VALUES.filter(
                  (slot) =>
                    slotState(selected, slot) !== "CONFIRMED" &&
                    canConfirm(slot),
                ).map((slot) => {
                  const otherSlot = slot === "MANAGEMENT" ? "ADMIN" : "MANAGEMENT";
                  const sameActor =
                    slotState(selected, otherSlot) === "CONFIRMED" &&
                    slotConfirmedBy(selected, otherSlot) === user?.id;
                  return (
                    <Button
                      key={slot}
                      size="sm"
                      onClick={() => setAction({ type: "confirm", slot })}
                      disabled={sameActor}
                      title={sameActor ? t("actions.sameActor") : undefined}
                    >
                      <Check className="me-1 h-4 w-4" aria-hidden="true" />
                      {t("actions.confirmSlot", {
                        slot: t(`slots.${slot}`),
                      })}
                    </Button>
                  );
                })}
                {SLOT_VALUES.filter(
                  (slot) =>
                    slotState(selected, slot) === "CONFIRMED" &&
                    canRevoke(slot),
                ).map((slot) => (
                  <Button
                    key={slot}
                    size="sm"
                    variant="outline"
                    onClick={() => setAction({ type: "revoke", slot })}
                  >
                    <Undo2 className="me-1 h-4 w-4" aria-hidden="true" />
                    {t("actions.revokeSlot", {
                      slot: t(`slots.${slot}`),
                    })}
                  </Button>
                ))}
                {canManageAdmissions &&
                  (selected.verification_status === "UNVERIFIED" ||
                    selected.verification_status === "DISPUTED") && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        setCandidateEditor({ candidate: selected })
                      }
                    >
                      <Pencil className="me-1 h-4 w-4" aria-hidden="true" />
                      {t("candidate.edit")}
                    </Button>
                  )}
                {canCorrect &&
                  selected.corrections_enabled !== false &&
                  selected.verification_status === "VERIFIED" &&
                  selected.original_admission_id !== selected.admission_id && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setAction({ type: "correct" })}
                    >
                      <UserRoundCheck className="me-1 h-4 w-4" aria-hidden="true" />
                      {t("actions.correctPointer")}
                    </Button>
                  )}
              </div>

              {!canManagement &&
                !canAdmin &&
                !canCorrect &&
                !canManageAdmissions &&
                selected.verification_status !== "VERIFIED" && (
                  <p className="text-sm text-muted-foreground">
                    {t("actions.noActions")}
                  </p>
                )}

              <section aria-labelledby="verification-acts-heading">
                <h3
                  id="verification-acts-heading"
                  className="flex items-center gap-2 text-sm font-semibold"
                >
                  <ClipboardCheck className="h-4 w-4 text-primary" aria-hidden="true" />
                  {t("detail.acts")}
                </h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t("detail.actsHint")}
                </p>
                {acts.loading ? (
                  <p className="mt-3 text-sm text-muted-foreground">
                    {tCommon("states.loading")}
                  </p>
                ) : acts.error ? (
                  <p className="mt-3 text-sm text-destructive">
                    {localizeError(acts.error).message}
                  </p>
                ) : (acts.data?.length ?? 0) === 0 ? (
                  <p className="mt-3 rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                    {t("detail.noActs")}
                  </p>
                ) : (
                  <ol className="mt-3 space-y-2">
                    {[...(acts.data ?? [])].reverse().map((act) => (
                      <li
                        key={act.id}
                        className="rounded-xl border border-border/80 bg-muted/20 p-3.5"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge
                              variant={act.action === "CONFIRM" ? "secondary" : "outline"}
                            >
                              {t(`actAction.${act.action}`)}
                            </Badge>
                            <span className="text-xs font-semibold">
                              {t(`slots.${act.slot}`)}
                            </span>
                            {act.resulting_verification_status && (
                              <TrustBadge
                                status={act.resulting_verification_status}
                              />
                            )}
                          </div>
                          <span className="text-xs text-muted-foreground">
                            {format.dateTime(new Date(act.acted_at), {
                              dateStyle: "medium",
                              timeStyle: "short",
                            })}
                          </span>
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {act.actor_name ?? act.actor_id}
                        </p>
                        <p className="mt-1 text-xs">
                          <span className="text-muted-foreground">
                            {t("detail.snapshot")}:{" "}
                          </span>
                          {act.candidate_intake_name ?? act.candidate_intake_id} ·{" "}
                          {act.candidate_program_name ?? "—"}
                        </p>
                        {act.action === "CONFIRM" ? (
                          <p className="mt-1 text-xs text-muted-foreground">
                            {act.evidence_type
                              ? t(`evidence.${act.evidence_type}`)
                              : "—"}
                            {act.evidence_reference
                              ? ` · ${act.evidence_reference}`
                              : ""}
                            {act.evidence_note ? ` · ${act.evidence_note}` : ""}
                          </p>
                        ) : (
                          <p className="mt-1 text-xs text-destructive">
                            {t("detail.revocationReason")}:{" "}
                            {act.revocation_reason ?? "—"}
                          </p>
                        )}
                      </li>
                    ))}
                  </ol>
                )}
              </section>

              {action && (
                <ActionDialog
                  action={action}
                  item={selected}
                  previousAdmission={
                    studentAdmissions.data?.find(
                      (admission) => admission.id === selected.original_admission_id,
                    ) ?? null
                  }
                  onClose={() => setAction(null)}
                  onDone={refreshAfterAction}
                />
              )}
            </>
          )}
        </DialogContent>
      </Dialog>

      {candidateEditor && (
        <MigrationCandidateDialog
          candidate={candidateEditor.candidate}
          onClose={() => setCandidateEditor(null)}
          onSaved={refreshAfterAction}
        />
      )}
    </AppShell>
  );
}

function SlotCard({
  item,
  slot,
  acts,
  format,
}: {
  item: MigrationQueueItem;
  slot: ConfirmationSlot;
  acts: VerificationAct[];
  format: ReturnType<typeof useFormatter>;
}) {
  const t = useTranslations("admissionVerification");
  const state = slotState(item, slot);
  const confirmedAt =
    slot === "MANAGEMENT"
      ? item.management_confirmed_at
      : item.admin_confirmed_at;
  const revokedAt =
    slot === "MANAGEMENT" ? item.management_revoked_at : item.admin_revoked_at;
  const act = latestConfirm(acts, slot);

  return (
    <div className="rounded-xl border border-border/80 bg-card p-4 shadow-card">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-sm font-semibold">{t(`slots.${slot}`)}</h4>
        <StatusBadge tone={toneForSlotState(state)}>
          {t(`slotState.${state}`)}
        </StatusBadge>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        {act?.actor_name ?? (confirmedAt ? t("detail.confirmed") : t("detail.notConfirmed"))}
      </p>
      {confirmedAt && (
        <p className="mt-1 text-xs tabular-nums text-muted-foreground">
          {format.dateTime(new Date(confirmedAt), {
            dateStyle: "medium",
            timeStyle: "short",
          })}
        </p>
      )}
      {revokedAt && (
        <p className="mt-1 text-xs text-warning">
          {t("detail.revokedAt", {
            date: format.dateTime(new Date(revokedAt), {
              dateStyle: "medium",
              timeStyle: "short",
            }),
          })}
        </p>
      )}
    </div>
  );
}

function ConflictSnapshots({ acts }: { acts: VerificationAct[] }) {
  const t = useTranslations("admissionVerification");
  const management = latestConfirm(acts, "MANAGEMENT");
  const admin = latestConfirm(acts, "ADMIN");
  return (
    <div className="mt-3 grid gap-2 sm:grid-cols-2">
      {[
        { slot: "MANAGEMENT" as const, act: management },
        { slot: "ADMIN" as const, act: admin },
      ].map(({ slot, act }) => (
        <div key={slot} className="rounded-lg border border-border/80 bg-card p-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            {t(`slots.${slot}`)}
          </p>
          <p className="mt-1 text-sm font-medium">
            {act?.candidate_intake_name ?? "—"}
          </p>
          <p className="text-xs text-muted-foreground">
            {act?.candidate_program_name ?? "—"}
          </p>
        </div>
      ))}
    </div>
  );
}

function ActionDialog({
  action,
  item,
  previousAdmission,
  onClose,
  onDone,
}: {
  action: Exclude<ActionState, null>;
  item: MigrationQueueItem;
  previousAdmission: AdmissionForPlacement | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const t = useTranslations("admissionVerification");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);
  const [evidenceType, setEvidenceType] =
    useState<EvidenceType>("ADMISSION_LETTER");
  const [evidenceReference, setEvidenceReference] = useState("");
  const [evidenceNote, setEvidenceNote] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);

  const isConfirm = action.type === "confirm";
  const isCorrect = action.type === "correct";
  const title =
    action.type === "confirm"
      ? t("confirm.title", { slot: t(`slots.${action.slot}`) })
      : action.type === "revoke"
        ? t("revoke.title", { slot: t(`slots.${action.slot}`) })
        : t("correct.title");
  const description =
    action.type === "confirm"
      ? t("confirm.description")
      : action.type === "revoke"
        ? t("revoke.description")
        : t("correct.description");

  const canSubmit =
    isConfirm
      ? evidenceReference.trim().length > 0
      : isCorrect
        ? reason.trim().length > 0 && confirmed
        : reason.trim().length > 0;

  async function submit() {
    setBusy(true);
    setFailure(null);
    try {
      if (action.type === "confirm") {
        const input: ConfirmationInput = {
          evidence_type: evidenceType,
          evidence_reference: evidenceReference.trim(),
          evidence_note: evidenceNote.trim() || undefined,
        };
        await admissionApi.confirm(item.student_id, item.admission_id, action.slot, input);
        toast.success(t("confirm.success"));
      } else if (action.type === "revoke") {
        await admissionApi.revoke(
          item.student_id,
          item.admission_id,
          action.slot,
          reason.trim(),
        );
        toast.success(t("revoke.success"));
      } else {
        await admissionApi.correctPointer(
          item.student_id,
          item.admission_id,
          reason.trim(),
          evidenceReference.trim(),
        );
        toast.success(t("correct.success"));
      }
      onDone();
      onClose();
    } catch (error) {
      setFailure(normalizeApiError(error, "migration verification action"));
      onDone();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        <div className="rounded-lg border border-border/80 bg-muted/25 p-3 text-sm">
          <p className="font-medium">{item.student_name}</p>
          <p className="text-xs text-muted-foreground">
            {item.admission_intake_name ?? "—"} ·{" "}
            {item.admitted_program_name ?? "—"}
          </p>
        </div>

        {isConfirm && (
          <>
            <label className="space-y-1.5 text-sm">
              <span className="font-medium">{t("confirm.evidenceType")}</span>
              <select
                value={evidenceType}
                onChange={(event) => setEvidenceType(event.target.value as EvidenceType)}
                className="h-10 w-full rounded-lg border border-input bg-card px-3 text-sm"
              >
                {EVIDENCE_VALUES.map((value) => (
                  <option key={value} value={value}>
                    {t(`evidence.${value}`)}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1.5 text-sm">
              <span className="font-medium">{t("confirm.evidenceReference")}</span>
              <Input
                value={evidenceReference}
                onChange={(event) => setEvidenceReference(event.target.value)}
                maxLength={500}
                placeholder={t("confirm.evidenceReferenceHint")}
              />
            </label>
            <label className="space-y-1.5 text-sm">
              <span className="font-medium">{t("confirm.evidenceNote")}</span>
              <Textarea
                value={evidenceNote}
                onChange={(event) => setEvidenceNote(event.target.value)}
                maxLength={2000}
                rows={3}
                placeholder={t("confirm.evidenceNoteHint")}
              />
            </label>
          </>
        )}

        {!isConfirm && (
          <label className="space-y-1.5 text-sm">
            <span className="font-medium">
              {isCorrect ? t("correct.reason") : t("revoke.reason")}
            </span>
            <Textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              maxLength={2000}
              rows={3}
              placeholder={t("revoke.reasonHint")}
            />
          </label>
        )}

        {isCorrect && (
          <>
            <div className="space-y-2 rounded-lg border border-border/80 bg-muted/20 p-3 text-sm">
              <div>
                <p className="text-xs text-muted-foreground">
                  {t("correct.previousPointer")}
                </p>
                <p className="font-medium">
                  {previousAdmission?.admission_intake_name ??
                    tCommon("states.notSet")}
                </p>
                <p className="text-xs text-muted-foreground">
                  {previousAdmission?.admitted_program_name ?? "—"}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">
                  {t("correct.newPointer")}
                </p>
                <p className="font-medium">
                  {item.admission_intake_name ?? tCommon("states.notSet")}
                </p>
                <p className="text-xs text-muted-foreground">
                  {item.admitted_program_name ?? "—"}
                </p>
              </div>
            </div>
            <label className="space-y-1.5 text-sm">
              <span className="font-medium">{t("correct.evidenceReference")}</span>
              <Input
                value={evidenceReference}
                onChange={(event) => setEvidenceReference(event.target.value)}
                maxLength={500}
                placeholder={t("confirm.evidenceReferenceHint")}
              />
            </label>
            <label className="flex items-start gap-2 rounded-lg border border-warning/35 bg-warning-soft/25 p-3 text-sm">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
                className="mt-0.5 h-4 w-4 shrink-0 accent-[hsl(var(--primary))]"
              />
              <span>{t("correct.confirm")}</span>
            </label>
          </>
        )}

        {failure && (
          <p role="alert" className="text-sm text-destructive">
            {localizeError(failure).message}
          </p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {tCommon("actions.cancel")}
          </Button>
          <Button onClick={() => void submit()} disabled={busy || !canSubmit}>
            {busy
              ? tCommon("states.saving")
              : isConfirm
                ? t("confirm.submit")
                : action.type === "revoke"
                  ? t("revoke.submit")
                  : t("correct.submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
