import { useQueryClient } from "@tanstack/react-query";
import { Dialog, DropdownMenu, Popover } from "radix-ui";
import { type ReactNode, useEffect, useRef, useState } from "react";
import {
  api,
  call,
  type CardDetail,
  type CardTile,
  type ColumnOut,
  colorVar,
  type CommentOut,
  type RichText,
  type UsersMap,
} from "../api/client";
import { applyTile, cardApi, keys, refreshAfterCardWrite, useCard, useTags, useUsers } from "../api/hooks";
import { describe } from "../lib/events";
import { ago, daysUntil, fullTime } from "../lib/time";
import { isEmptyDoc, RichTextEditor, RichTextView } from "./RichText";
import { isDemo } from "../lib/demo";
import { Avatar, Button, ConfirmButton, errorText, Icon, Kbd, useToast } from "./ui";

const QUICK_REACTIONS = ["👍", "🎉", "❤️", "👀", "🙏"];

type Props = {
  number: number | null;
  columns: ColumnOut[];
  onClose: () => void;
};

export function CardSheet({ number, columns, onClose }: Props) {
  const card = useCard(number);
  return (
    <Dialog.Root open={number != null} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-30 bg-black/25" />
        <Dialog.Content
          className="fixed top-0 right-0 bottom-0 z-40 flex w-full max-w-[720px] flex-col border-l border-line bg-surface shadow-lift outline-none"
          aria-describedby={undefined}
        >
          {card.data ? (
            <SheetBody detail={card.data} columns={columns} onClose={onClose} />
          ) : (
            <div className="p-6 text-ink-2">
              <Dialog.Title className="sr-only">Card</Dialog.Title>
              {card.isError ? errorText(card.error) : "Loading…"}
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function useCardActions(detail: CardDetail) {
  const qc = useQueryClient();
  const toast = useToast();
  const tile = detail.card;
  return async function run(fn: () => Promise<{ card: CardTile; users: UsersMap } | void>, okText?: string) {
    try {
      const res = await fn();
      if (res) applyTile(qc, res.card, res.users);
      if (okText) toast(okText, "info");
    } catch (err) {
      toast(errorText(err));
    }
    refreshAfterCardWrite(qc, tile.board_id, tile.number);
    void qc.invalidateQueries({ queryKey: keys.card(tile.number) });
  };
}

function SheetBody({ detail, columns, onClose }: { detail: CardDetail; columns: ColumnOut[]; onClose: () => void }) {
  const tile = detail.card;
  const run = useCardActions(detail);
  const users = useUsers();
  const people = users.data ?? [];
  const isDraft = tile.status === "draft";
  const column = columns.find((c) => c.id === tile.column_id);
  const qc = useQueryClient();

  const where = isDraft
    ? "Draft"
    : tile.state === "done"
      ? "Done"
      : tile.state === "not_now"
        ? "Not Now"
        : (column?.name ?? "Maybe?");

  return (
    <>
      <header className="flex items-center gap-2 border-b border-line px-4 py-3 md:px-5">
        <span className="font-mono text-[12px] text-ink-3">#{tile.number}</span>
        <span
          className="inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-2 py-0.5 text-[12px] font-medium text-ink-2"
          title={detail.board_name}
        >
          {column && <span className="size-2 rounded-full" style={{ background: colorVar(column.color) }} />}
          {detail.board_name} · {where}
        </span>
        {tile.golden && (
          <span className="inline-flex items-center gap-1 rounded-full bg-gold-soft px-2 py-0.5 text-[12px] font-medium text-gold">
            <Icon name="star" size={12} /> Golden
          </span>
        )}
        <span className="flex-1" />
        <Dialog.Close asChild>
          <button type="button" className="rounded p-1 text-ink-3 hover:bg-surface-2" aria-label="Close card">
            <Icon name="x" />
          </button>
        </Dialog.Close>
      </header>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto md:flex-row md:overflow-hidden">
        <div className="min-w-0 flex-1 px-4 py-4 md:overflow-y-auto md:px-5">
          <TitleField detail={detail} onSave={(title) => run(() => cardApi.edit(tile.number, { title, version: tile.version }))} />
          {tile.closing_soon && tile.auto_postpone_at && (
            <p className="mt-2 flex items-center gap-1.5 rounded-md bg-surface-2 px-2.5 py-1.5 text-[12.5px] text-ink-2">
              <Icon name="clock" size={14} />
              Nobody has touched this in a while. It moves to Not Now in {daysUntil(tile.auto_postpone_at)} days unless
              someone does.
            </p>
          )}

          <section className="mt-4">
            <RichTextEditor
              key={tile.id}
              value={detail.description}
              users={people}
              placeholder="Add a description…"
              resetKey={tile.version}
              onCommit={(doc) => run(() => cardApi.edit(tile.number, { description: doc }))}
              className="rounded-lg border border-transparent px-2 py-1 hover:border-line focus-within:border-accent"
            />
          </section>

          <Steps detail={detail} />
          <Attachments detail={detail} />

          <section className="mt-6">
            <h3 className="mb-2 text-[12px] font-semibold tracking-wide text-ink-3 uppercase">Discussion</h3>
            <Comments detail={detail} />
            {!isDraft && <CommentComposer number={tile.number} boardId={tile.board_id} />}
          </section>

          <section className="mt-6 mb-4">
            <h3 className="mb-2 text-[12px] font-semibold tracking-wide text-ink-3 uppercase">History</h3>
            <ol className="space-y-1.5 border-l border-line pl-3">
              {detail.events.map((e) => (
                <li key={e.id} className="text-[12.5px] text-ink-2">
                  <span>{describe(e, detail.users)}</span>
                  <span className="ml-1.5 text-ink-3" title={fullTime(e.created_at)}>
                    {ago(e.created_at)}
                  </span>
                </li>
              ))}
              <li className="text-[12.5px] text-ink-3">
                Created by {detail.users[tile.created_by]?.display_name ?? "someone"} · {fullTime(tile.created_at)}
              </li>
            </ol>
          </section>
        </div>

        <aside className="shrink-0 space-y-4 border-t border-line bg-surface-2/50 px-4 py-4 md:w-56 md:overflow-y-auto md:border-t-0 md:border-l">
          {isDraft ? (
            <Button variant="primary" className="w-full justify-center" onClick={() => run(() => cardApi.publish(tile.number), "Published to Maybe?")}>
              Publish to Maybe?
            </Button>
          ) : (
            <div className="space-y-1.5">
              <MoveMenu tile={tile} columns={columns} run={run} />
              {tile.state === "active" && (
                <Button className="w-full" onClick={() => run(() => cardApi.postpone(tile.number))}>
                  <Icon name="clock" size={14} /> Not Now
                </Button>
              )}
              {tile.state === "not_now" && (
                <Button className="w-full" onClick={() => run(() => cardApi.resume(tile.number))}>
                  <Icon name="undo" size={14} /> Back to Maybe?
                </Button>
              )}
              {tile.state === "done" ? (
                <Button className="w-full" onClick={() => run(() => cardApi.reopen(tile.number))}>
                  <Icon name="undo" size={14} /> Reopen
                </Button>
              ) : (
                <Button className="w-full" onClick={() => run(() => cardApi.close(tile.number))}>
                  <Icon name="check" size={14} /> Done
                </Button>
              )}
              <Button className="w-full" onClick={() => run(() => cardApi.gild(tile.number, !tile.golden))}>
                <Icon name="star" size={14} className={tile.golden ? "text-gold" : "text-ink-3"} />
                {tile.golden ? "Remove golden ticket" : "Golden ticket"}
              </Button>
            </div>
          )}

          <SidePicker
            label="Assignees"
            selected={tile.assignee_ids}
            options={people.map((u) => ({ id: u.id, label: u.display_name, user: u }))}
            render={(id) => (
              <span className="flex items-center gap-1.5 text-[13px]">
                <Avatar user={detail.users[id] ?? people.find((p) => p.id === id)} size={18} />
                {detail.users[id]?.display_name ?? people.find((p) => p.id === id)?.display_name}
              </span>
            )}
            onToggle={(id, on) => run(() => cardApi.assign(tile.number, id, on))}
          />
          <TagPicker tile={tile} run={run} />

          <div className="space-y-1.5 border-t border-line pt-3">
            <ToggleRow
              icon="eye"
              on={detail.watching}
              label={detail.watching ? "Watching" : "Watch"}
              hint="Get notified about changes"
              onClick={() =>
                run(async () => {
                  const path = { params: { path: { number: tile.number } } };
                  await call(detail.watching ? api.DELETE("/api/cards/{number}/watch", path) : api.PUT("/api/cards/{number}/watch", path));
                })
              }
            />
            <ToggleRow
              icon="pin"
              on={detail.pinned}
              label={detail.pinned ? "Pinned" : "Pin"}
              hint="Keep it on your shortlist"
              onClick={() =>
                run(async () => {
                  const path = { params: { path: { number: tile.number } } };
                  await call(detail.pinned ? api.DELETE("/api/cards/{number}/pin", path) : api.PUT("/api/cards/{number}/pin", path));
                  void qc.invalidateQueries({ queryKey: keys.pins });
                })
              }
            />
          </div>

          {detail.can_delete && (
            <div className="border-t border-line pt-3">
              <ConfirmButton
                prompt={`Delete #${tile.number}? Its history stays in the timeline.`}
                confirmLabel="Delete card"
                onConfirm={async () => {
                  await run(async () => {
                    await call(api.DELETE("/api/cards/{number}", { params: { path: { number: tile.number } } }));
                  });
                  onClose();
                }}
                className="inline-flex w-full items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium text-danger hover:bg-danger-soft"
              >
                <Icon name="trash" size={14} /> Delete card
              </ConfirmButton>
            </div>
          )}
        </aside>
      </div>
    </>
  );
}

function TitleField({ detail, onSave }: { detail: CardDetail; onSave: (title: string) => void }) {
  const [value, setValue] = useState(detail.card.title);
  useEffect(() => setValue(detail.card.title), [detail.card.title]);
  return (
    <>
      <Dialog.Title className="sr-only">{`#${detail.card.number} ${detail.card.title}`}</Dialog.Title>
      <textarea
        value={value}
        rows={1}
        onChange={(e) => setValue(e.target.value.replace(/\n/g, " "))}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            e.currentTarget.blur();
          }
        }}
        onBlur={() => {
          const next = value.trim();
          if (next && next !== detail.card.title) onSave(next);
          else setValue(detail.card.title);
        }}
        aria-label="Card title"
        className="field-sizing-content w-full resize-none rounded-md border border-transparent bg-transparent px-2 py-1 text-[20px] leading-snug font-semibold text-ink outline-none hover:border-line focus:border-accent"
      />
    </>
  );
}

type Run = (fn: () => Promise<{ card: CardTile; users: UsersMap } | void>, okText?: string) => Promise<void>;

function MoveMenu({ tile, columns, run }: { tile: CardTile; columns: ColumnOut[]; run: Run }) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <Button variant="primary" className="w-full justify-between">
          Move to… <Icon name="chevron-down" size={14} />
        </Button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={4} className="z-50 min-w-48 rounded-lg border border-line bg-surface p-1 shadow-lift">
          {tile.state === "active" && tile.column_id && (
            <MenuItem onSelect={() => run(() => cardApi.untriage(tile.number))}>Maybe?</MenuItem>
          )}
          {columns
            .filter((c) => c.id !== tile.column_id || tile.state !== "active")
            .map((c) => (
              <MenuItem key={c.id} onSelect={() => run(() => cardApi.triage(tile.number, c.id))}>
                <span className="size-2 rounded-full" style={{ background: colorVar(c.color) }} />
                {c.name}
              </MenuItem>
            ))}
          {columns.length === 0 && <p className="px-2 py-1.5 text-[12px] text-ink-3">This board has no columns yet.</p>}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

function MenuItem({ children, onSelect }: { children: ReactNode; onSelect: () => void }) {
  return (
    <DropdownMenu.Item
      onSelect={onSelect}
      className="flex cursor-default items-center gap-2 rounded-md px-2 py-1.5 text-[13px] outline-none data-[highlighted]:bg-accent-soft"
    >
      {children}
    </DropdownMenu.Item>
  );
}

function ToggleRow({ icon, on, label, hint, onClick }: { icon: "eye" | "pin"; on: boolean; label: string; hint: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={hint}
      aria-pressed={on}
      className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-[13px] ${on ? "bg-accent-soft text-ink" : "text-ink-2 hover:bg-surface-3"}`}
    >
      <Icon name={icon} size={14} />
      {label}
    </button>
  );
}

function SidePicker({
  label,
  selected,
  options,
  render,
  onToggle,
}: {
  label: string;
  selected: string[];
  options: { id: string; label: string; user?: import("../api/client").UserBrief }[];
  render: (id: string) => ReactNode;
  onToggle: (id: string, on: boolean) => void;
}) {
  const [q, setQ] = useState("");
  const shown = options.filter((o) => o.label.toLowerCase().includes(q.toLowerCase())).slice(0, 30);
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[12px] font-semibold tracking-wide text-ink-3 uppercase">{label}</span>
        <Popover.Root>
          <Popover.Trigger asChild>
            <button type="button" className="rounded p-0.5 text-ink-3 hover:bg-surface-3" aria-label={`Edit ${label}`}>
              <Icon name="plus" size={14} />
            </button>
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Content align="end" sideOffset={4} className="z-50 w-56 rounded-lg border border-line bg-surface p-1 shadow-lift">
              <input
                autoFocus
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Find someone…"
                className="mb-1 w-full rounded-md border border-line bg-surface-2 px-2 py-1 text-[13px] outline-none"
              />
              <div className="max-h-60 overflow-y-auto">
                {shown.map((o) => {
                  const on = selected.includes(o.id);
                  return (
                    <button
                      type="button"
                      key={o.id}
                      onClick={() => onToggle(o.id, !on)}
                      className="flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-[13px] hover:bg-surface-2"
                    >
                      <span className={`size-3.5 rounded border ${on ? "border-accent bg-accent" : "border-line-strong"}`} />
                      {o.user && <Avatar user={o.user} size={18} />}
                      {o.label}
                    </button>
                  );
                })}
              </div>
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
      </div>
      {selected.length === 0 ? (
        <p className="text-[12.5px] text-ink-3">Nobody yet</p>
      ) : (
        <ul className="space-y-1">
          {selected.map((id) => (
            <li key={id}>{render(id)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function TagPicker({ tile, run }: { tile: CardTile; run: Run }) {
  const tags = useTags();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const toast = useToast();
  const all = tags.data ?? [];
  const has = new Set(tile.tags.map((t) => t.id));
  const shown = all.filter((t) => t.name.toLowerCase().includes(q.toLowerCase().replace(/^#/, "")));
  const exact = all.some((t) => t.name.toLowerCase() === q.trim().toLowerCase().replace(/^#/, ""));

  async function createAndAdd() {
    try {
      const tag = await call(api.POST("/api/tags", { body: { name: q.trim(), color: "teal" } }));
      void qc.invalidateQueries({ queryKey: keys.tags });
      setQ("");
      await run(() => cardApi.tag(tile.number, tag.id, true));
    } catch (err) {
      toast(errorText(err));
    }
  }

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[12px] font-semibold tracking-wide text-ink-3 uppercase">Tags</span>
        <Popover.Root>
          <Popover.Trigger asChild>
            <button type="button" className="rounded p-0.5 text-ink-3 hover:bg-surface-3" aria-label="Edit tags">
              <Icon name="plus" size={14} />
            </button>
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Content align="end" sideOffset={4} className="z-50 w-56 rounded-lg border border-line bg-surface p-1 shadow-lift">
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  if (q.trim() && !exact) void createAndAdd();
                }}
              >
                <input
                  autoFocus
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="Find or create a tag…"
                  className="mb-1 w-full rounded-md border border-line bg-surface-2 px-2 py-1 text-[13px] outline-none"
                />
              </form>
              <div className="max-h-60 overflow-y-auto">
                {shown.map((t) => (
                  <button
                    type="button"
                    key={t.id}
                    onClick={() => run(() => cardApi.tag(tile.number, t.id, !has.has(t.id)))}
                    className="flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-[13px] hover:bg-surface-2"
                  >
                    <span className={`size-3.5 rounded border ${has.has(t.id) ? "border-accent bg-accent" : "border-line-strong"}`} />
                    <span className="size-2 rounded-full" style={{ background: colorVar(t.color) }} />
                    {t.name}
                  </button>
                ))}
                {q.trim() && !exact && (
                  <button type="button" onClick={() => void createAndAdd()} className="w-full rounded-md px-2 py-1 text-left text-[13px] text-accent hover:bg-surface-2">
                    Create “{q.trim().replace(/^#/, "")}”
                  </button>
                )}
              </div>
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
      </div>
      {tile.tags.length === 0 ? (
        <p className="text-[12.5px] text-ink-3">No tags</p>
      ) : (
        <div className="flex flex-wrap gap-1">
          {tile.tags.map((t) => (
            <span key={t.id} className="inline-flex items-center gap-1 rounded-full bg-surface px-2 py-0.5 text-[12px] text-ink-2 ring-1 ring-line">
              <span className="size-1.5 rounded-full" style={{ background: colorVar(t.color) }} />
              {t.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function Steps({ detail }: { detail: CardDetail }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [body, setBody] = useState("");
  const tile = detail.card;
  const refresh = () => refreshAfterCardWrite(qc, tile.board_id, tile.number);

  async function act(fn: () => Promise<unknown>) {
    try {
      await fn();
    } catch (err) {
      toast(errorText(err));
    }
    refresh();
  }

  return (
    <section className="mt-5">
      <h3 className="mb-2 flex items-center gap-2 text-[12px] font-semibold tracking-wide text-ink-3 uppercase">
        Steps
        {detail.steps.length > 0 && (
          <span className="font-normal normal-case">
            {detail.steps.filter((s) => s.completed_at).length} of {detail.steps.length}
          </span>
        )}
      </h3>
      <ul className="space-y-0.5">
        {detail.steps.map((s) => (
          <li key={s.id} className="group flex items-center gap-2 rounded-md px-1 py-0.5 hover:bg-surface-2">
            <input
              type="checkbox"
              checked={!!s.completed_at}
              onChange={(e) =>
                act(() =>
                  call(api.PATCH("/api/steps/{step_id}", { params: { path: { step_id: s.id } }, body: { completed: e.target.checked } })),
                )
              }
              className="size-4 accent-[var(--accent)]"
              aria-label={s.body}
            />
            <span className={`flex-1 text-[13.5px] ${s.completed_at ? "text-ink-3 line-through" : ""}`}>{s.body}</span>
            <button
              type="button"
              onClick={() => act(() => call(api.DELETE("/api/steps/{step_id}", { params: { path: { step_id: s.id } } })))}
              className="rounded p-0.5 text-ink-3 opacity-0 group-hover:opacity-100 hover:text-danger focus:opacity-100"
              aria-label={`Remove step ${s.body}`}
            >
              <Icon name="x" size={13} />
            </button>
          </li>
        ))}
      </ul>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const text = body.trim();
          if (!text) return;
          setBody("");
          void act(() =>
            call(api.POST("/api/cards/{number}/steps", { params: { path: { number: tile.number } }, body: { body: text } })),
          );
        }}
        className="mt-1 flex items-center gap-2 px-1"
      >
        <Icon name="plus" size={14} className="text-ink-3" />
        <input
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="Add a step"
          className="flex-1 bg-transparent py-1 text-[13.5px] outline-none placeholder:text-ink-3"
        />
      </form>
    </section>
  );
}

function Attachments({ detail }: { detail: CardDetail }) {
  const qc = useQueryClient();
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const tile = detail.card;

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    for (const file of Array.from(files)) {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`/api/cards/${tile.number}/attachments`, { method: "POST", body: form });
      if (!res.ok) {
        const problem = (await res.json().catch(() => ({}))) as { detail?: string };
        toast(problem.detail ?? `Couldn't upload ${file.name}`);
      }
    }
    setBusy(false);
    refreshAfterCardWrite(qc, tile.board_id, tile.number);
  }

  return (
    <section className="mt-5">
      <div className="mb-2 flex items-center gap-2">
        <h3 className="text-[12px] font-semibold tracking-wide text-ink-3 uppercase">Attachments</h3>
        <span className="flex-1" />
        <Button variant="ghost" className="!py-0.5" onClick={() => input.current?.click()} disabled={busy}>
          <Icon name="clip" size={14} /> {busy ? "Uploading…" : "Attach"}
        </Button>
        <input ref={input} type="file" multiple hidden onChange={(e) => void upload(e.target.files)} />
      </div>
      {detail.attachments.length > 0 && (
        <ul className="grid gap-2 sm:grid-cols-2">
          {detail.attachments.map((a) => (
            <li key={a.id} className="group flex items-center gap-2 rounded-lg border border-line px-2 py-1.5">
              <Icon name="clip" size={14} className="text-ink-3" />
              {isDemo ? (
                <span className="min-w-0 flex-1 truncate text-[13px]" title="Downloads are off in the preview">
                  {a.filename}
                </span>
              ) : (
                <a href={`/api/attachments/${a.id}`} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate text-[13px] hover:underline">
                  {a.filename}
                </a>
              )}
              <span className="text-[11px] text-ink-3">{formatBytes(a.bytes)}</span>
              <button
                type="button"
                onClick={async () => {
                  try {
                    await call(api.DELETE("/api/attachments/{attachment_id}", { params: { path: { attachment_id: a.id } } }));
                  } catch (err) {
                    toast(errorText(err));
                  }
                  refreshAfterCardWrite(qc, tile.board_id, tile.number);
                }}
                className="rounded p-0.5 text-ink-3 opacity-0 group-hover:opacity-100 hover:text-danger focus:opacity-100"
                aria-label={`Remove ${a.filename}`}
              >
                <Icon name="x" size={13} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function Comments({ detail }: { detail: CardDetail }) {
  if (detail.comments.length === 0) return <p className="mb-3 text-[13px] text-ink-3">No comments yet.</p>;
  return (
    <ul className="mb-3 space-y-3">
      {detail.comments.map((c) => (
        <CommentItem key={c.id} comment={c} detail={detail} />
      ))}
    </ul>
  );
}

function CommentItem({ comment, detail }: { comment: CommentOut; detail: CardDetail }) {
  const qc = useQueryClient();
  const toast = useToast();
  const author = detail.users[comment.author_id];
  const tile = detail.card;
  const refresh = () => void qc.invalidateQueries({ queryKey: keys.card(tile.number) });

  async function react(emoji: string, on: boolean) {
    const path = { params: { path: { comment_id: comment.id, emoji } } };
    try {
      await call(on ? api.PUT("/api/comments/{comment_id}/reactions/{emoji}", path) : api.DELETE("/api/comments/{comment_id}/reactions/{emoji}", path));
    } catch (err) {
      toast(errorText(err));
    }
    refresh();
  }

  return (
    <li className="flex gap-2.5">
      <Avatar user={author} size={26} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="text-[13px] font-semibold">{author?.display_name ?? "Someone"}</span>
          <span className="text-[11.5px] text-ink-3" title={fullTime(comment.created_at)}>
            {ago(comment.created_at)}
            {comment.edited_at && " · edited"}
          </span>
        </div>
        <RichTextView doc={comment.body} className="text-[13.5px]" />
        <div className="mt-1 flex flex-wrap items-center gap-1">
          {comment.reactions.map((r) => (
            <button
              type="button"
              key={r.emoji}
              onClick={() => react(r.emoji, !r.mine)}
              title={r.user_ids.map((id) => detail.users[id]?.display_name ?? "?").join(", ")}
              className={`rounded-full px-1.5 py-[1px] text-[12px] ring-1 ${r.mine ? "bg-accent-soft ring-accent" : "ring-line hover:bg-surface-2"}`}
            >
              {r.emoji} {r.count}
            </button>
          ))}
          <Popover.Root>
            <Popover.Trigger asChild>
              <button type="button" className="rounded-full px-1.5 text-[12px] text-ink-3 ring-1 ring-line hover:bg-surface-2" aria-label="Add reaction">
                +
              </button>
            </Popover.Trigger>
            <Popover.Portal>
              <Popover.Content sideOffset={4} className="z-50 flex gap-1 rounded-full border border-line bg-surface p-1 shadow-lift">
                {QUICK_REACTIONS.map((e) => (
                  <Popover.Close asChild key={e}>
                    <button type="button" onClick={() => react(e, true)} className="rounded-full px-1.5 text-[15px] hover:bg-surface-2">
                      {e}
                    </button>
                  </Popover.Close>
                ))}
              </Popover.Content>
            </Popover.Portal>
          </Popover.Root>
        </div>
      </div>
    </li>
  );
}

function CommentComposer({ number, boardId }: { number: number; boardId: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const users = useUsers();
  const [doc, setDoc] = useState<RichText | null>(null);
  const [reset, setReset] = useState(0);
  const [busy, setBusy] = useState(false);

  async function post(body: RichText) {
    if (busy || isEmptyDoc(body)) return;
    setBusy(true);
    try {
      await call(api.POST("/api/cards/{number}/comments", { params: { path: { number } }, body: { body } }));
      setDoc(null);
      setReset((r) => r + 1);
    } catch (err) {
      toast(errorText(err));
    } finally {
      setBusy(false);
    }
    refreshAfterCardWrite(qc, boardId, number);
  }

  return (
    <div className="rounded-lg border border-line focus-within:border-accent">
      <RichTextEditor
        value={null}
        resetKey={reset}
        users={users.data ?? []}
        placeholder="Comment, or @mention someone…"
        onChange={setDoc}
        onSubmit={post}
        className="px-3 py-1.5 text-[13.5px]"
      />
      <div className="flex items-center justify-end gap-2 border-t border-line px-2 py-1.5">
        <span className="text-[11px] text-ink-3">
          <Kbd>⌘</Kbd> <Kbd>Enter</Kbd>
        </span>
        <Button variant="primary" disabled={busy || isEmptyDoc(doc)} onClick={() => doc && void post(doc)}>
          Comment
        </Button>
      </div>
    </div>
  );
}
