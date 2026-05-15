"use client";

import { useEffect, useMemo, useState } from "react";
import { Ban, Pencil } from "lucide-react";

import { API_BASE } from "@/lib/api";
import { MODULES, type ModuleId, type PermissionLevel } from "@/lib/modules";

type Role = "admin" | "member";
type UserStatus = "active" | "invited" | "disabled";
type Permissions = Record<ModuleId, PermissionLevel>;
const CURRENT_USER_ROLE: Role = "admin";

interface TeamUser {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
  role: Role;
  permissions: Permissions;
  status: UserStatus;
}

const EMPTY_PERMISSIONS = Object.fromEntries(
  MODULES.map((module) => [module.id, "none"]),
) as Permissions;

function defaultPermissions(role: Role): Permissions {
  if (role === "admin") {
    return Object.fromEntries(MODULES.map((module) => [module.id, "editor"])) as Permissions;
  }
  return Object.fromEntries(
    MODULES.map((module) => [module.id, module.id === "settings" ? "none" : "viewer"]),
  ) as Permissions;
}

function initials(firstName: string, lastName: string) {
  return `${firstName.slice(0, 1)}${lastName.slice(0, 1)}`.toUpperCase() || "?";
}

function permissionStyle(level: PermissionLevel) {
  if (level === "editor") return "border-[var(--ch-accent)] bg-[var(--ch-accent)] text-[var(--ch-accent-text)]";
  if (level === "viewer") return "border-[var(--ch-accent)]/45 bg-transparent text-[var(--ch-accent)]";
  return "border-[var(--ch-border)] bg-[var(--ch-surface)] text-[var(--ch-text-muted)]";
}

async function fetchUsers(): Promise<TeamUser[]> {
  const response = await fetch(`${API_BASE}/users`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Could not load users (${response.status})`);
  return await response.json() as TeamUser[];
}

async function sendInvite(payload: {
  first_name: string;
  last_name: string;
  email: string;
  role: Role;
  permissions: Permissions;
}) {
  const response = await fetch(`${API_BASE}/users/invite`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(errorBody.detail || `Invite failed (${response.status})`);
  }
  return await response.json() as { id: string; email: string; status: string };
}

function AccessPills({ permissions }: { permissions: Permissions }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {MODULES.map((module) => (
        <span
          key={module.id}
          title={`${module.label}: ${permissions[module.id] || "none"}`}
          className={`rounded-full border px-2 py-1 text-[11px] font-semibold ${permissionStyle(permissions[module.id] || "none")}`}
        >
          {module.label}
        </span>
      ))}
    </div>
  );
}

function InviteModal({
  onClose,
  onSuccess,
}: {
  onClose: () => void;
  onSuccess: (message: string) => void;
}) {
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [permissions, setPermissions] = useState<Permissions>(() => defaultPermissions("member"));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function updateRole(nextRole: Role) {
    setRole(nextRole);
    setPermissions(defaultPermissions(nextRole));
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await sendInvite({
        first_name: firstName,
        last_name: lastName,
        email,
        role,
        permissions,
      });
      onSuccess(`Invite sent to ${email}`);
      onClose();
    } catch (inviteError) {
      setError(inviteError instanceof Error ? inviteError.message : "Invite failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4">
      <form
        onSubmit={handleSubmit}
        className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)] p-6 shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-[var(--ch-text-primary)]">Invite User</h2>
            <p className="mt-1 text-sm text-[var(--ch-text-secondary)]">Set role and module access before sending.</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-[var(--ch-border)] px-3 py-1.5 text-sm text-[var(--ch-text-secondary)] hover:text-[var(--ch-text-primary)]"
          >
            Close
          </button>
        </div>

        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-2 text-sm text-[var(--ch-text-secondary)]">
            First name
            <input
              required
              value={firstName}
              onChange={(event) => setFirstName(event.target.value)}
              className="rounded-lg border border-[var(--ch-border)] bg-[var(--ch-page-bg)] px-3 py-2.5 text-[var(--ch-text-primary)] outline-none focus:border-[var(--ch-accent)] focus:ring-2 focus:ring-[var(--ch-focus-ring)]"
            />
          </label>
          <label className="flex flex-col gap-2 text-sm text-[var(--ch-text-secondary)]">
            Last name
            <input
              required
              value={lastName}
              onChange={(event) => setLastName(event.target.value)}
              className="rounded-lg border border-[var(--ch-border)] bg-[var(--ch-page-bg)] px-3 py-2.5 text-[var(--ch-text-primary)] outline-none focus:border-[var(--ch-accent)] focus:ring-2 focus:ring-[var(--ch-focus-ring)]"
            />
          </label>
          <label className="flex flex-col gap-2 text-sm text-[var(--ch-text-secondary)] sm:col-span-2">
            Email
            <input
              required
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="rounded-lg border border-[var(--ch-border)] bg-[var(--ch-page-bg)] px-3 py-2.5 text-[var(--ch-text-primary)] outline-none focus:border-[var(--ch-accent)] focus:ring-2 focus:ring-[var(--ch-focus-ring)]"
            />
          </label>
        </div>

        <div className="mt-5">
          <p className="mb-2 text-sm text-[var(--ch-text-secondary)]">Role</p>
          <div className="flex gap-3">
            {(["admin", "member"] as Role[]).map((option) => (
              <label
                key={option}
                className="flex items-center gap-2 rounded-lg border border-[var(--ch-border)] bg-[var(--ch-surface)] px-3 py-2 text-sm text-[var(--ch-text-secondary)]"
              >
                <input
                  type="radio"
                  checked={role === option}
                  onChange={() => updateRole(option)}
                  className="accent-[var(--ch-accent)]"
                />
                {option === "admin" ? "Admin" : "Member"}
              </label>
            ))}
          </div>
        </div>

        <div className="mt-6 overflow-hidden rounded-xl border border-[var(--ch-border)]">
          <div className="grid grid-cols-[1fr_110px_110px_110px] bg-[var(--ch-surface)] px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-[var(--ch-text-muted)]">
            <span>Module</span>
            <span>No Access</span>
            <span>Viewer</span>
            <span>Editor</span>
          </div>
          {MODULES.map((module) => (
            <div
              key={module.id}
              className="grid grid-cols-[1fr_110px_110px_110px] items-center border-t border-[var(--ch-border)] px-4 py-3 text-sm"
            >
              <span className="font-medium text-[var(--ch-text-primary)]">{module.label}</span>
              {(["none", "viewer", "editor"] as PermissionLevel[]).map((level) => (
                <label key={level} className="flex justify-center">
                  <input
                    type="radio"
                    name={`permission-${module.id}`}
                    checked={permissions[module.id] === level}
                    onChange={() => setPermissions((current) => ({ ...current, [module.id]: level }))}
                    className="accent-[var(--ch-accent)]"
                  />
                </label>
              ))}
            </div>
          ))}
        </div>

        {error && (
          <div className="mt-4 rounded-lg border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] px-3 py-2 text-sm text-[var(--ch-error-text)]">
            {error}
          </div>
        )}

        <div className="mt-6 flex justify-end">
          <button
            type="submit"
            disabled={submitting}
            className="rounded-lg bg-[var(--ch-accent)] px-5 py-2.5 text-sm font-bold text-[var(--ch-accent-text)] hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-55"
          >
            {submitting ? "Sending..." : "Send Invite"}
          </button>
        </div>
      </form>
    </div>
  );
}

export default function UsersPage() {
  const [users, setUsers] = useState<TeamUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [inviteOpen, setInviteOpen] = useState(false);

  async function loadUsers() {
    try {
      const result = await fetchUsers();
      setUsers(result);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not load users.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    fetchUsers()
      .then((result) => {
        if (cancelled) return;
        setUsers(result);
        setError(null);
      })
      .catch((loadError) => {
        if (cancelled) return;
        setError(loadError instanceof Error ? loadError.message : "Could not load users.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const rows = useMemo(() => users, [users]);

  return (
    <div className="px-8 py-8">
      <header className="mb-6 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-[var(--ch-text-primary)]">Team</h1>
          <p className="mt-2 text-sm text-[var(--ch-text-secondary)]">
            Manage team members and their module access.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setSuccess(null);
            setInviteOpen(true);
          }}
          className="rounded-lg bg-[var(--ch-accent)] px-4 py-2 text-sm font-bold text-[var(--ch-accent-text)] hover:brightness-105"
        >
          Invite User
        </button>
      </header>

      {success && (
        <div className="mb-4 rounded-xl border border-[var(--ch-success-border)] bg-[var(--ch-success-bg)] px-4 py-3 text-sm text-[var(--ch-success-text)]">
          {success}
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-xl border border-[var(--ch-error-border)] bg-[var(--ch-error-bg)] px-4 py-3 text-sm text-[var(--ch-error-text)]">
          {error}
        </div>
      )}

      <section className="overflow-hidden rounded-xl border border-[var(--ch-border)] bg-[var(--ch-surface)]">
        <div className="grid grid-cols-[1fr_1.15fr_110px_1.8fr_110px_100px] gap-4 border-b border-[var(--ch-border)] px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-[var(--ch-text-muted)]">
          <span>Name</span>
          <span>Email</span>
          <span>Role</span>
          <span>Module Access</span>
          <span>Status</span>
          <span>Actions</span>
        </div>

        {loading ? (
          <div className="p-8 text-center text-sm text-[var(--ch-text-muted)]">Loading team...</div>
        ) : rows.length === 0 ? (
          <div className="p-8 text-center text-sm text-[var(--ch-text-muted)]">
            No team members yet. Invite someone to get started.
          </div>
        ) : (
          rows.map((user) => (
            <div
              key={user.id}
              className="grid grid-cols-[1fr_1.15fr_110px_1.8fr_110px_100px] items-center gap-4 border-b border-[var(--ch-border)] px-4 py-4 last:border-b-0"
            >
              <div className="flex min-w-0 items-center gap-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[var(--ch-accent)] text-xs font-bold text-[var(--ch-accent-text)]">
                  {initials(user.first_name, user.last_name)}
                </span>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-[var(--ch-text-primary)]">
                    {user.first_name} {user.last_name}
                  </p>
                </div>
              </div>
              <p className="truncate text-sm text-[var(--ch-text-secondary)]">{user.email}</p>
              <span className="w-fit rounded-full border border-[var(--ch-border)] bg-[var(--ch-surface)] px-2.5 py-1 text-xs font-semibold text-[var(--ch-text-secondary)]">
                {user.role === "admin" ? "Admin" : "Member"}
              </span>
              <AccessPills permissions={{ ...EMPTY_PERMISSIONS, ...user.permissions }} />
              <span className="w-fit rounded-full border border-[var(--ch-success-border)] bg-[var(--ch-success-bg)] px-2.5 py-1 text-xs font-semibold text-[var(--ch-success-text)]">
                {user.status.charAt(0).toUpperCase() + user.status.slice(1)}
              </span>
              {CURRENT_USER_ROLE === "admin" ? (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    title="Edit"
                    className="rounded-lg border border-[var(--ch-border)] p-2 text-[var(--ch-text-secondary)] hover:text-[var(--ch-text-primary)]"
                  >
                    <Pencil size={15} />
                  </button>
                  <button
                    type="button"
                    title="Disable"
                    className="rounded-lg border border-[var(--ch-border)] p-2 text-[var(--ch-text-secondary)] hover:border-[var(--ch-error-border)] hover:text-[var(--ch-error-text)]"
                  >
                    <Ban size={15} />
                  </button>
                </div>
              ) : (
                <span className="text-xs text-[var(--ch-text-muted)]">Admin only</span>
              )}
            </div>
          ))
        )}
      </section>

      {inviteOpen && (
        <InviteModal
          onClose={() => setInviteOpen(false)}
          onSuccess={(message) => {
            setSuccess(message);
            void loadUsers();
          }}
        />
      )}
    </div>
  );
}
