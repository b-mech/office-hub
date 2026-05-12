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
  if (level === "editor") return "border-[#FAC775] bg-[#FAC775] text-[#0f1117]";
  if (level === "viewer") return "border-[#FAC775]/45 bg-transparent text-[#FAC775]";
  return "border-white/10 bg-white/5 text-white/35";
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
        className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-xl border border-white/10 bg-[#11141b] p-6 shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-white">Invite User</h2>
            <p className="mt-1 text-sm text-white/45">Set role and module access before sending.</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-white/10 px-3 py-1.5 text-sm text-white/55 hover:text-white"
          >
            Close
          </button>
        </div>

        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-2 text-sm text-white/70">
            First name
            <input
              required
              value={firstName}
              onChange={(event) => setFirstName(event.target.value)}
              className="rounded-lg border border-white/10 bg-black/25 px-3 py-2.5 text-white outline-none focus:border-[#FAC775] focus:ring-2 focus:ring-[#FAC775]/15"
            />
          </label>
          <label className="flex flex-col gap-2 text-sm text-white/70">
            Last name
            <input
              required
              value={lastName}
              onChange={(event) => setLastName(event.target.value)}
              className="rounded-lg border border-white/10 bg-black/25 px-3 py-2.5 text-white outline-none focus:border-[#FAC775] focus:ring-2 focus:ring-[#FAC775]/15"
            />
          </label>
          <label className="flex flex-col gap-2 text-sm text-white/70 sm:col-span-2">
            Email
            <input
              required
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="rounded-lg border border-white/10 bg-black/25 px-3 py-2.5 text-white outline-none focus:border-[#FAC775] focus:ring-2 focus:ring-[#FAC775]/15"
            />
          </label>
        </div>

        <div className="mt-5">
          <p className="mb-2 text-sm text-white/70">Role</p>
          <div className="flex gap-3">
            {(["admin", "member"] as Role[]).map((option) => (
              <label
                key={option}
                className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/70"
              >
                <input
                  type="radio"
                  checked={role === option}
                  onChange={() => updateRole(option)}
                  className="accent-[#FAC775]"
                />
                {option === "admin" ? "Admin" : "Member"}
              </label>
            ))}
          </div>
        </div>

        <div className="mt-6 overflow-hidden rounded-xl border border-white/10">
          <div className="grid grid-cols-[1fr_110px_110px_110px] bg-white/5 px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-white/35">
            <span>Module</span>
            <span>No Access</span>
            <span>Viewer</span>
            <span>Editor</span>
          </div>
          {MODULES.map((module) => (
            <div
              key={module.id}
              className="grid grid-cols-[1fr_110px_110px_110px] items-center border-t border-white/10 px-4 py-3 text-sm"
            >
              <span className="font-medium text-white">{module.label}</span>
              {(["none", "viewer", "editor"] as PermissionLevel[]).map((level) => (
                <label key={level} className="flex justify-center">
                  <input
                    type="radio"
                    name={`permission-${module.id}`}
                    checked={permissions[module.id] === level}
                    onChange={() => setPermissions((current) => ({ ...current, [module.id]: level }))}
                    className="accent-[#FAC775]"
                  />
                </label>
              ))}
            </div>
          ))}
        </div>

        {error && (
          <div className="mt-4 rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
            {error}
          </div>
        )}

        <div className="mt-6 flex justify-end">
          <button
            type="submit"
            disabled={submitting}
            className="rounded-lg bg-[#FAC775] px-5 py-2.5 text-sm font-bold text-[#0f1117] hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-55"
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
          <h1 className="text-3xl font-semibold tracking-tight text-white">Team</h1>
          <p className="mt-2 text-sm text-white/50">
            Manage team members and their module access.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setSuccess(null);
            setInviteOpen(true);
          }}
          className="rounded-lg bg-[#FAC775] px-4 py-2 text-sm font-bold text-[#0f1117] hover:brightness-105"
        >
          Invite User
        </button>
      </header>

      {success && (
        <div className="mb-4 rounded-xl border border-emerald-400/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100">
          {success}
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      )}

      <section className="overflow-hidden rounded-xl border border-white/10 bg-white/[0.04]">
        <div className="grid grid-cols-[1fr_1.15fr_110px_1.8fr_110px_100px] gap-4 border-b border-white/10 px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-white/35">
          <span>Name</span>
          <span>Email</span>
          <span>Role</span>
          <span>Module Access</span>
          <span>Status</span>
          <span>Actions</span>
        </div>

        {loading ? (
          <div className="p-8 text-center text-sm text-white/35">Loading team...</div>
        ) : rows.length === 0 ? (
          <div className="p-8 text-center text-sm text-white/35">
            No team members yet. Invite someone to get started.
          </div>
        ) : (
          rows.map((user) => (
            <div
              key={user.id}
              className="grid grid-cols-[1fr_1.15fr_110px_1.8fr_110px_100px] items-center gap-4 border-b border-white/10 px-4 py-4 last:border-b-0"
            >
              <div className="flex min-w-0 items-center gap-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[#FAC775] text-xs font-bold text-[#0f1117]">
                  {initials(user.first_name, user.last_name)}
                </span>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-white">
                    {user.first_name} {user.last_name}
                  </p>
                </div>
              </div>
              <p className="truncate text-sm text-white/55">{user.email}</p>
              <span className="w-fit rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-xs font-semibold text-white/60">
                {user.role === "admin" ? "Admin" : "Member"}
              </span>
              <AccessPills permissions={{ ...EMPTY_PERMISSIONS, ...user.permissions }} />
              <span className="w-fit rounded-full border border-emerald-400/30 bg-emerald-500/10 px-2.5 py-1 text-xs font-semibold text-emerald-200">
                {user.status.charAt(0).toUpperCase() + user.status.slice(1)}
              </span>
              {CURRENT_USER_ROLE === "admin" ? (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    title="Edit"
                    className="rounded-lg border border-white/10 p-2 text-white/45 hover:text-white"
                  >
                    <Pencil size={15} />
                  </button>
                  <button
                    type="button"
                    title="Disable"
                    className="rounded-lg border border-white/10 p-2 text-white/45 hover:border-red-400/35 hover:text-red-200"
                  >
                    <Ban size={15} />
                  </button>
                </div>
              ) : (
                <span className="text-xs text-white/30">Admin only</span>
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
