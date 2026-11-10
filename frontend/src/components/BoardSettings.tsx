import { useQueryClient } from "@tanstack/react-query";
import { Dialog } from "radix-ui";
import { useEffect, useState } from "react";
import { api, type BoardSnapshot, COLUMN_COLORS, call, colorVar, type ColumnOut } from "../api/client";
import { keys, useUsers } from "../api/hooks";
import { Avatar, Button, ConfirmButton, errorText, Icon, useToast } from "./ui";

const PERIODS = [3, 7, 14, 30, 60, 90, 180, 365];

export function BoardSettings({ snap, open, onOpenChange }: { snap: BoardSnapshot; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const board = snap.board;
  const [name, setName] = useState(board.name);
  useEffect(() => setName(board.name), [board.name]);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: keys.board(board.id) });
    void qc.invalidateQueries({ queryKey: keys.boards });
  };
  async function act(fn: () => Promise<unknown>) {
    try {
      await fn();
    } catch (err) {
      toast(errorText(err));
    }
    refresh();
  }
  const patch = (body: Record<string, unknown>) =>
    act(() => call(api.PATCH("/api/boards/{board_id}", { params: { path: { board_id: board.id } }, body })));

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-30 bg-black/25" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed top-1/2 left-1/2 z-40 max-h-[85%] w-[560px] max-w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl border border-line bg-surface p-5 shadow-lift"
        >
          <div className="mb-4 flex items-center">
            <Dialog.Title className="text-[16px] font-semibold">Board settings</Dialog.Title>
            <span className="flex-1" />
            <Dialog.Close asChild>
              <button type="button" className="rounded p-1 text-ink-3 hover:bg-surface-2" aria-label="Close">
                <Icon name="x" />
              </button>
            </Dialog.Close>
          </div>

          {!board.can_admin && (
            <p className="mb-4 rounded-md bg-surface-2 px-3 py-2 text-[13px] text-ink-2">
              Only the board’s creator or an admin can change these settings.
            </p>
          )}

          <fieldset disabled={!board.can_admin} className="space-y-5">
            <label className="block">
              <span className="mb-1 block text-[12px] font-semibold text-ink-2">Name</span>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                onBlur={() => name.trim() && name !== board.name && patch({ name })}
                className="w-full rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-[14px] outline-none focus:border-accent"
              />
            </label>

            <div>
              <span className="mb-1 block text-[12px] font-semibold text-ink-2">Auto-postpone</span>
              <p className="mb-2 text-[12.5px] text-ink-3">
                Open cards nobody touches for this long move to Not Now. A “closing soon” warning shows at 75%.
              </p>
              <select
                value={board.auto_postpone_days ?? ""}
                onChange={(e) => patch({ auto_postpone_days: e.target.value ? Number(e.target.value) : null })}
                className="rounded-md border border-line bg-surface-2 px-2 py-1.5 text-[13px]"
              >
                <option value="">Workspace default</option>
                {PERIODS.map((d) => (
                  <option key={d} value={d}>
                    {d} days
                  </option>
                ))}
              </select>
            </div>

            <Columns snap={snap} act={act} />
            <Access snap={snap} patch={patch} act={act} />

            <div className="border-t border-line pt-4">
              <Button variant="danger" onClick={() => patch({ archived: !board.archived_at })}>
                {board.archived_at ? "Unarchive board" : "Archive board"}
              </Button>
            </div>
          </fieldset>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Columns({ snap, act }: { snap: BoardSnapshot; act: (fn: () => Promise<unknown>) => Promise<void> }) {
  const [name, setName] = useState("");
  const [color, setColor] = useState<string>("blue");
  const cols = snap.columns;
  const move = (col: ColumnOut, dir: -1 | 1) => {
    const i = cols.findIndex((c) => c.id === col.id);
    const j = i + dir;
    if (j < 0 || j >= cols.length) return;
    const body = dir === -1 ? { below: cols[j]!.id } : { above: cols[j]!.id };
    return act(() => call(api.PATCH("/api/columns/{column_id}", { params: { path: { column_id: col.id } }, body })));
  };
  return (
    <div>
      <span className="mb-1 block text-[12px] font-semibold text-ink-2">Columns</span>
      <ul className="mb-2 space-y-1">
        {cols.map((c, i) => (
          <li key={c.id} className="flex items-center gap-2 rounded-md border border-line px-2 py-1">
            <ColorPicker
              value={c.color}
              onChange={(next) =>
                act(() => call(api.PATCH("/api/columns/{column_id}", { params: { path: { column_id: c.id } }, body: { color: next } })))
              }
            />
            <input
              defaultValue={c.name}
              onBlur={(e) =>
                e.target.value.trim() &&
                e.target.value !== c.name &&
                act(() =>
                  call(api.PATCH("/api/columns/{column_id}", { params: { path: { column_id: c.id } }, body: { name: e.target.value } })),
                )
              }
              aria-label="Column name"
              className="min-w-0 flex-1 bg-transparent text-[13px] outline-none"
            />
            <button type="button" disabled={i === 0} onClick={() => move(c, -1)} className="rounded px-1 text-ink-3 hover:bg-surface-2 disabled:opacity-30" aria-label="Move left">
              ←
            </button>
            <button type="button" disabled={i === cols.length - 1} onClick={() => move(c, 1)} className="rounded px-1 text-ink-3 hover:bg-surface-2 disabled:opacity-30" aria-label="Move right">
              →
            </button>
            <ConfirmButton
              compact
              prompt={`Delete ${c.name}? Its open cards go back to Maybe?.`}
              onConfirm={() =>
                void act(() => call(api.DELETE("/api/columns/{column_id}", { params: { path: { column_id: c.id } } })))
              }
              className="rounded p-0.5 text-ink-3 hover:text-danger"
              ariaLabel={`Delete ${c.name}`}
            >
              <Icon name="trash" size={14} />
            </ConfirmButton>
          </li>
        ))}
      </ul>
      <form
        className="flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (!name.trim()) return;
          const body = { name: name.trim(), color, above: cols.at(-1)?.id ?? null };
          setName("");
          void act(() => call(api.POST("/api/boards/{board_id}/columns", { params: { path: { board_id: snap.board.id } }, body })));
        }}
      >
        <ColorPicker value={color} onChange={setColor} />
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="New column, e.g. Doing"
          className="min-w-0 flex-1 rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-[13px] outline-none focus:border-accent"
        />
        <Button type="submit">Add</Button>
      </form>
    </div>
  );
}

function ColorPicker({ value, onChange }: { value: string; onChange: (c: string) => void }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label="Colour"
      className="w-7 cursor-pointer appearance-none rounded-full border-2 border-surface text-transparent"
      style={{ background: colorVar(value), height: 18, width: 18 }}
    >
      {COLUMN_COLORS.map((c) => (
        <option key={c} value={c} style={{ color: "initial" }}>
          {c}
        </option>
      ))}
    </select>
  );
}

function Access({
  snap,
  patch,
  act,
}: {
  snap: BoardSnapshot;
  patch: (body: Record<string, unknown>) => Promise<void>;
  act: (fn: () => Promise<unknown>) => Promise<void>;
}) {
  const users = useUsers();
  const board = snap.board;
  const [ids, setIds] = useState<string[] | null>(null);
  useEffect(() => {
    if (board.all_access) return;
    void call(api.GET("/api/boards/{board_id}/access", { params: { path: { board_id: board.id } } })).then((r) => setIds(r.user_ids));
  }, [board.id, board.all_access]);

  const save = (next: string[]) => {
    setIds(next);
    return act(() => call(api.PUT("/api/boards/{board_id}/access", { params: { path: { board_id: board.id } }, body: { user_ids: next } })));
  };

  return (
    <div>
      <span className="mb-1 block text-[12px] font-semibold text-ink-2">Who can see this board</span>
      <div className="space-y-1 text-[13px]">
        <label className="flex items-center gap-2">
          <input type="radio" checked={board.all_access} onChange={() => patch({ all_access: true })} />
          Everyone in Seltzer
        </label>
        <label className="flex items-center gap-2">
          <input type="radio" checked={!board.all_access} onChange={() => patch({ all_access: false })} />
          Only selected people (plus the creator and admins)
        </label>
      </div>
      {!board.all_access && (
        <ul className="mt-2 max-h-48 space-y-0.5 overflow-y-auto rounded-md border border-line p-1">
          {(users.data ?? []).map((u) => {
            const on = ids?.includes(u.id) ?? false;
            return (
              <li key={u.id}>
                <label className="flex items-center gap-2 rounded px-1.5 py-1 hover:bg-surface-2">
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() => ids && void save(on ? ids.filter((x) => x !== u.id) : [...ids, u.id])}
                  />
                  <Avatar user={u} size={18} />
                  <span className="flex-1">{u.display_name}</span>
                  <span className="text-[11px] text-ink-3">{u.email}</span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
