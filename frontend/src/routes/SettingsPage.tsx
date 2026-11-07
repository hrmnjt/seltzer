import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, call, type UserOut } from "../api/client";
import { keys, useMe } from "../api/hooks";
import { Avatar, errorText, useToast } from "../components/ui";
import { ago } from "../lib/time";

const PERIODS = [3, 7, 14, 30, 60, 90, 180, 365];

/** Workspace members and roles, and the default auto-postpone period. */
export function SettingsPage() {
  const me = useMe();
  const qc = useQueryClient();
  const toast = useToast();
  const isAdmin = me.data?.user.role === "owner" || me.data?.user.role === "admin";
  const isOwner = me.data?.user.role === "owner";
  const settings = useQuery({ queryKey: keys.settings, queryFn: () => call(api.GET("/api/settings")) });
  const people = useQuery({
    queryKey: ["users", "all"],
    queryFn: () => call(api.GET("/api/users", { params: { query: { include_inactive: true } } })),
  });

  async function act(fn: () => Promise<unknown>) {
    try {
      await fn();
    } catch (err) {
      toast(errorText(err));
    }
    void qc.invalidateQueries({ queryKey: ["users"] });
    void qc.invalidateQueries({ queryKey: keys.settings });
    void qc.invalidateQueries({ queryKey: keys.me });
  }
  const updateUser = (u: UserOut, body: { role?: UserOut["role"]; active?: boolean }) =>
    act(() => call(api.PATCH("/api/users/{user_id}", { params: { path: { user_id: u.id } }, body })));

  return (
    <div className="mx-auto max-w-3xl space-y-8 px-4 py-6 sm:px-6">
      <section>
        <h1 className="mb-1 text-[18px] font-semibold">Workspace settings</h1>
        <p className="text-[13px] text-ink-2">
          Databricks decides who can open Seltzer (CAN USE on the app). Members of the owner group become owners when
          they sign in.
        </p>
      </section>

      <section>
        <h2 className="mb-2 text-[14px] font-semibold">Default auto-postpone period</h2>
        <select
          disabled={!isAdmin}
          value={settings.data?.default_auto_postpone_days ?? 30}
          onChange={(e) =>
            act(() => call(api.PATCH("/api/settings", { body: { default_auto_postpone_days: Number(e.target.value) } })))
          }
          className="rounded-md border border-line bg-surface px-2 py-1.5 text-[13px]"
        >
          {PERIODS.map((d) => (
            <option key={d} value={d}>
              {d} days
            </option>
          ))}
        </select>
        <p className="mt-1 text-[12.5px] text-ink-3">Boards without their own period use this one.</p>
      </section>

      <section>
        <h2 className="mb-2 text-[14px] font-semibold">People</h2>
        <div className="overflow-x-auto">
        <table className="w-full min-w-[480px] text-[13px]">
          <thead className="text-left text-[11.5px] text-ink-3 uppercase">
            <tr>
              <th className="py-1.5 font-semibold">Person</th>
              <th className="py-1.5 font-semibold">Role</th>
              <th className="py-1.5 font-semibold">Last seen</th>
              <th className="py-1.5 font-semibold" />
            </tr>
          </thead>
          <tbody>
            {people.data?.map((u) => (
              <tr key={u.id} className={`border-t border-line ${u.active ? "" : "opacity-50"}`}>
                <td className="py-2">
                  <span className="flex items-center gap-2">
                    <Avatar user={u} size={22} />
                    <span>
                      <span className="block font-medium">{u.display_name}</span>
                      <span className="block text-[11.5px] text-ink-3">{u.email}</span>
                    </span>
                  </span>
                </td>
                <td className="py-2">
                  <select
                    value={u.role}
                    disabled={!isAdmin || (u.role === "owner" && !isOwner)}
                    onChange={(e) => updateUser(u, { role: e.target.value as UserOut["role"] })}
                    className="rounded-md border border-line bg-surface px-1.5 py-1"
                  >
                    {isOwner || u.role === "owner" ? <option value="owner">Owner</option> : null}
                    <option value="admin">Admin</option>
                    <option value="member">Member</option>
                  </select>
                </td>
                <td className="py-2 text-ink-3">{u.last_seen_at ? ago(u.last_seen_at) : "never"}</td>
                <td className="py-2 text-right">
                  {isAdmin && u.id !== me.data?.user.id && (
                    <button type="button" onClick={() => updateUser(u, { active: !u.active })} className="text-[12.5px] text-accent hover:underline">
                      {u.active ? "Deactivate" : "Restore"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </section>
    </div>
  );
}
