"use client";

import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";
import {
  KeyRound,
  Link2,
  Pencil,
  Plus,
  ShieldCheck,
  UserCheck,
  UserX,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { accountApi } from "@/lib/account-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { Input } from "@/components/ui/input";
import { DataTable, type Column } from "@/components/ui/data-table";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/ui/status-badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "@/components/ui/toast";
import { ROLE_NAMES, type Account, type RoleName } from "@/types/account";

const STAFF_ROLES: RoleName[] = ["TEACHER", "MANAGEMENT", "ADMIN"];

interface Credential {
  email: string;
  password?: string;
  /** Activation link, present only in environments that return it. */
  activationUrl?: string;
}

export default function AccountsPage() {
  const t = useTranslations("institutional");
  const tCommon = useTranslations("common");
  const { hasPermission } = useAuth();
  const localizeError = useErrorMessage();
  const [search, setSearch] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [roleTarget, setRoleTarget] = useState<Account | null>(null);
  const [editTarget, setEditTarget] = useState<Account | null>(null);
  const [credential, setCredential] = useState<Credential | null>(null);

  const canManage = hasPermission("users.manage");
  const fetchAccounts = useCallback(
    () =>
      accountApi.list({
        page: 1,
        page_size: 100,
        search: search.trim() || undefined,
      }),
    [search],
  );
  const { data, loading, error, refetch } = useApi(
    fetchAccounts,
    [search],
    "accounts",
  );

  const localized = localizeError(error);

  if (!canManage) {
    return (
      <AppShell>
        <EmptyState title={t("managerOnly")} message={t("managerOnlyHint")} />
      </AppShell>
    );
  }

  const columns: Column<Account>[] = [
    {
      key: "person",
      header: tCommon("labels.name"),
      cell: (account) => (
        <div className="min-w-0">
          <p className="truncate font-medium">{account.full_name}</p>
          <p className="truncate text-xs text-muted-foreground" dir="ltr">
            {account.email}
          </p>
        </div>
      ),
    },
    {
      key: "roles",
      header: t("role"),
      cell: (account) => (
        <div className="flex flex-wrap gap-1">
          {account.roles.map((role) => (
            <Badge key={role.id} variant="secondary">
              {role.name}
            </Badge>
          ))}
        </div>
      ),
    },
    {
      key: "staff",
      header: t("staffProfile"),
      hideOnMobile: true,
      cell: (account) =>
        account.has_staff_record ? (
          <div className="text-sm">
            <p>{account.staff_department || tCommon("states.notSet")}</p>
            <p className="font-mono text-xs text-muted-foreground" dir="ltr">
              {account.staff_id || t("staffNumberMissing")}
            </p>
          </div>
        ) : (
          <span className="text-sm text-muted-foreground">
            {tCommon("states.notAvailable")}
          </span>
        ),
    },
    {
      key: "status",
      header: tCommon("labels.status"),
      cell: (account) => (
        <StatusBadge tone={account.is_active ? "success" : "muted"}>
          {account.is_active ? tCommon("states.active") : tCommon("states.inactive")}
        </StatusBadge>
      ),
    },
    {
      key: "actions",
      header: tCommon("labels.actions"),
      className: "text-end",
      cell: (account) => (
        <div className="flex flex-wrap justify-end gap-1">
          <Button
            variant="ghost"
            size="icon"
            aria-label={`${tCommon("actions.edit")} ${account.full_name}`}
            title={tCommon("actions.edit")}
            onClick={() => setEditTarget(account)}
          >
            <Pencil className="h-4 w-4" aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={`${t("changeRole")} ${account.full_name}`}
            title={t("changeRole")}
            onClick={() => setRoleTarget(account)}
          >
            <ShieldCheck className="h-4 w-4" aria-hidden="true" />
          </Button>
          {account.roles.some((role) => role.name === "STUDENT") && (
            <ConfirmDialog
              title={t("issueActivation")}
              description={t("issueActivationDescription", {
                name: account.full_name,
              })}
              confirmLabel={t("issueActivation")}
              triggerLabel={t("issueActivation")}
              triggerIcon={<Link2 className="h-4 w-4" aria-hidden="true" />}
              size="icon"
              onConfirm={async () => {
                const result = await accountApi.issueActivation(account.id, {
                  identity_verified: true,
                  verification_reference: "COUNTER-CHECK",
                });
                setCredential({
                  email: account.email,
                  activationUrl: result.activation_url ?? undefined,
                });
                if (!result.activation_url) {
                  toast.success(t("activationIssuedNoLink"));
                }
              }}
            />
          )}
          <ConfirmDialog
            title={t("resetPassword")}
            description={t("resetPasswordDescription", { name: account.full_name })}
            confirmLabel={t("resetPassword")}
            triggerLabel={t("resetPassword")}
            triggerIcon={<KeyRound className="h-4 w-4" aria-hidden="true" />}
            size="icon"
            onConfirm={async () => {
              const result = await accountApi.resetPassword(account.id);
              setCredential({
                email: account.email,
                password: result.temporary_password ?? "",
              });
            }}
          />
          <ConfirmDialog
            title={
              account.is_active ? t("deactivate") : tCommon("states.active")
            }
            description={
              account.is_active
                ? t("deactivateDescription", { name: account.full_name })
                : t("activateDescription", { name: account.full_name })
            }
            confirmLabel={
              account.is_active ? t("deactivate") : tCommon("states.active")
            }
            triggerLabel={
              account.is_active ? t("deactivate") : tCommon("states.active")
            }
            triggerIcon={
              account.is_active ? (
                <UserX className="h-4 w-4" aria-hidden="true" />
              ) : (
                <UserCheck className="h-4 w-4" aria-hidden="true" />
              )
            }
            size="icon"
            variant={account.is_active ? "ghost" : "ghost"}
            onConfirm={async () => {
              await accountApi.setActive(account.id, !account.is_active);
              toast.success(t("statusChanged"));
            }}
            onDone={refetch}
          />
        </div>
      ),
    },
  ];

  return (
    <AppShell>
      <PageHeader
        title={t("accountsTitle")}
        description={t("accountsSubtitle")}
        breadcrumbs={[
          { label: tCommon("labels.overview"), href: "/app" },
          { label: t("accountsTitle") },
        ]}
        actions={
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="me-1.5 h-4 w-4" aria-hidden="true" />
            {t("createStaff")}
          </Button>
        }
      />

      <Card className="mb-4">
        <CardContent className="p-4">
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={tCommon("labels.searchPlaceholder")}
            aria-label={tCommon("labels.search")}
            className="sm:max-w-sm"
          />
        </CardContent>
      </Card>

      {error ? (
        <ErrorState
          message={localized.message}
          hint={localized.hint}
          onRetry={refetch}
        />
      ) : (
        <DataTable
          columns={columns}
          rows={data?.items ?? []}
          rowKey={(account) => account.id}
          loading={loading}
          emptyTitle={t("noAccounts")}
          emptyMessage={t("noAccountsHint")}
        />
      )}

      {createOpen && (
        <CreateStaffDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          onCreated={(result) => {
            setCreateOpen(false);
            setCredential({
              email: result.account.email,
              password: result.temporary_password ?? "",
            });
            refetch();
          }}
        />
      )}

      {roleTarget && (
        <RoleChangeDialog
          account={roleTarget}
          open={Boolean(roleTarget)}
          onOpenChange={(open) => !open && setRoleTarget(null)}
          onSaved={() => {
            setRoleTarget(null);
            refetch();
          }}
        />
      )}

      {editTarget && (
        <EditStaffDialog
          account={editTarget}
          open={Boolean(editTarget)}
          onOpenChange={(open) => !open && setEditTarget(null)}
          onSaved={() => {
            setEditTarget(null);
            refetch();
          }}
        />
      )}

      {credential?.activationUrl && (
        <Dialog open onOpenChange={() => setCredential(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{t("activationLink")}</DialogTitle>
              <DialogDescription>{t("activationLinkHint")}</DialogDescription>
            </DialogHeader>
            <div className="space-y-2 rounded-lg border bg-muted/30 p-4">
              <p className="text-xs text-muted-foreground">{credential.email}</p>
              <p className="break-all font-mono text-sm" dir="ltr">
                {credential.activationUrl}
              </p>
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  void navigator.clipboard.writeText(credential.activationUrl ?? "");
                  toast.success(t("copied"));
                }}
              >
                {t("copyLink")}
              </Button>
              <Button onClick={() => setCredential(null)}>
                {tCommon("actions.done")}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}

      {credential?.password && (
        <Dialog open onOpenChange={() => setCredential(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{t("temporaryPassword")}</DialogTitle>
              <DialogDescription>{t("temporaryPasswordHint")}</DialogDescription>
            </DialogHeader>
            <div className="space-y-2 rounded-lg border bg-muted/30 p-4">
              <p className="text-xs text-muted-foreground">{credential.email}</p>
              <p className="break-all font-mono text-lg font-semibold" dir="ltr">
                {credential.password}
              </p>
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  void navigator.clipboard.writeText(credential.password ?? "");
                  toast.success(t("copied"));
                }}
              >
                {t("copyPassword")}
              </Button>
              <Button onClick={() => setCredential(null)}>
                {tCommon("actions.done")}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </AppShell>
  );
}

function CreateStaffDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (result: Awaited<ReturnType<typeof accountApi.create>>) => void;
}) {
  const t = useTranslations("institutional");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    role: "TEACHER" as RoleName,
    staff_id: "",
    department: "",
    title: "",
  });
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);

  const update = (key: keyof typeof form, value: string) =>
    setForm((current) => ({ ...current, [key]: value }));

  async function submit() {
    setBusy(true);
    setFailure(null);
    try {
      const result = await accountApi.create({
        full_name: form.full_name.trim(),
        email: form.email.trim(),
        roles: [form.role],
        staff_id: form.staff_id.trim() || undefined,
        department: form.department.trim() || undefined,
        title: form.title.trim() || undefined,
      });
      toast.success(t("staffAccountCreated"));
      onCreated(result);
    } catch (error) {
      setFailure(normalizeApiError(error, "create staff account"));
    } finally {
      setBusy(false);
    }
  }

  const ready = form.full_name.trim() && form.email.trim();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("createStaff")}</DialogTitle>
          <DialogDescription>{t("createStaffDescription")}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={tCommon("labels.name")} value={form.full_name} onChange={(v) => update("full_name", v)} />
          <Field label={tCommon("labels.email")} value={form.email} type="email" onChange={(v) => update("email", v)} />
          <label className="space-y-1.5 text-sm">
            <span className="font-medium">{t("role")}</span>
            <select
              value={form.role}
              onChange={(event) => update("role", event.target.value)}
              className="h-10 w-full rounded-md border border-input bg-background px-3"
            >
              {STAFF_ROLES.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
          </label>
          <Field label={t("staffNumber")} value={form.staff_id} onChange={(v) => update("staff_id", v)} help={t("staffNumberHint")} />
          <Field label={t("department")} value={form.department} onChange={(v) => update("department", v)} />
          <Field label={t("jobTitle")} value={form.title} onChange={(v) => update("title", v)} />
        </div>
        {failure && (
          <p role="alert" className="text-sm text-destructive">
            {localizeError(failure).message}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {tCommon("actions.cancel")}
          </Button>
          <Button onClick={() => void submit()} disabled={busy || !ready}>
            {busy ? tCommon("states.saving") : tCommon("actions.create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RoleChangeDialog({
  account,
  open,
  onOpenChange,
  onSaved,
}: {
  account: Account;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const t = useTranslations("institutional");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();
  const current = (account.roles[0]?.name ?? "STUDENT") as RoleName;
  const [role, setRole] = useState<RoleName>(current);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);

  async function submit() {
    setBusy(true);
    setFailure(null);
    try {
      await accountApi.setRoles(account.id, [role], reason.trim());
      toast.success(t("roleSaved"));
      onSaved();
    } catch (error) {
      setFailure(normalizeApiError(error, "change role"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("changeRole")}</DialogTitle>
          <DialogDescription>
            {t("roleChangeDescription", { name: account.full_name })}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <label className="space-y-1.5 text-sm">
            <span className="font-medium">{t("role")}</span>
            <select
              value={role}
              onChange={(event) => setRole(event.target.value as RoleName)}
              className="h-10 w-full rounded-md border border-input bg-background px-3"
            >
              {ROLE_NAMES.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="font-medium">{t("reason")}</span>
            <Input
              value={reason}
              maxLength={500}
              onChange={(event) => setReason(event.target.value)}
              placeholder={t("reasonHint")}
            />
          </label>
          <p className="text-xs text-muted-foreground">{t("roleChangeAuditHint")}</p>
        </div>
        {failure && (
          <p role="alert" className="text-sm text-destructive">
            {localizeError(failure).message}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {tCommon("actions.cancel")}
          </Button>
          <Button
            onClick={() => void submit()}
            disabled={busy || reason.trim().length < 3 || role === current}
          >
            {busy ? tCommon("states.saving") : tCommon("actions.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function EditStaffDialog({
  account,
  open,
  onOpenChange,
  onSaved,
}: {
  account: Account;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const t = useTranslations("institutional");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();
  const [form, setForm] = useState({
    full_name: account.full_name,
    email: account.email,
    staff_id: account.staff_id ?? "",
    department: account.staff_department ?? "",
    title: account.staff_title ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);

  async function submit() {
    setBusy(true);
    setFailure(null);
    try {
      await accountApi.update(account.id, {
        full_name: form.full_name.trim(),
        email: form.email.trim(),
        staff_id: form.staff_id.trim() || null,
        department: form.department.trim() || null,
        title: form.title.trim() || null,
      });
      toast.success(t("staffAccountUpdated"));
      onSaved();
    } catch (error) {
      setFailure(normalizeApiError(error, "update staff account"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("editProfile")}</DialogTitle>
          <DialogDescription>{t("editProfileDescription")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <label className="space-y-1.5 text-sm">
            <span className="font-medium">{tCommon("labels.name")}</span>
            <Input
              value={form.full_name}
              onChange={(event) =>
                setForm((current) => ({ ...current, full_name: event.target.value }))
              }
            />
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="font-medium">{tCommon("labels.email")}</span>
            <Input
              type="email"
              value={form.email}
              onChange={(event) =>
                setForm((current) => ({ ...current, email: event.target.value }))
              }
            />
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="font-medium">{t("staffNumber")}</span>
            <Input
              value={form.staff_id}
              onChange={(event) =>
                setForm((current) => ({ ...current, staff_id: event.target.value }))
              }
            />
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="font-medium">{t("department")}</span>
            <Input
              value={form.department}
              onChange={(event) =>
                setForm((current) => ({ ...current, department: event.target.value }))
              }
            />
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="font-medium">{t("jobTitle")}</span>
            <Input
              value={form.title}
              onChange={(event) =>
                setForm((current) => ({ ...current, title: event.target.value }))
              }
            />
          </label>
        </div>
        {failure && (
          <p role="alert" className="text-sm text-destructive">
            {localizeError(failure).message}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {tCommon("actions.cancel")}
          </Button>
          <Button onClick={() => void submit()} disabled={busy}>
            {busy ? tCommon("states.saving") : tCommon("actions.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  help,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  help?: string;
}) {
  return (
    <label className="space-y-1.5 text-sm">
      <span className="font-medium">{label}</span>
      <Input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
      {help && <span className="block text-xs text-muted-foreground">{help}</span>}
    </label>
  );
}
