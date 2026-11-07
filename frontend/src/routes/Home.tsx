import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { api, call, type EventOut } from "../api/client";
import { keys, useBoards, usePins, useTimeline } from "../api/hooks";
import { Avatar, Button, errorText, Icon, useToast } from "../components/ui";
import { describe } from "../lib/events";
import { dayKey, dayLabel, fullTime } from "../lib/time";

export function Home() {
  const boards = useBoards();
  const timeline = useTimeline();
  const pins = usePins();

  return (
    <div className="mx-auto grid max-w-6xl gap-8 px-4 py-6 sm:px-6 lg:grid-cols-[minmax(0,1fr)_360px]">
      <div className="space-y-8">
        <section>
          <div className="mb-3 flex items-center">
            <h1 className="text-[18px] font-semibold">Boards</h1>
            <span className="flex-1" />
            <NewBoard />
          </div>
          {boards.data?.length === 0 && (
            <div className="rounded-xl border border-dashed border-line-strong p-6 text-[13.5px] text-ink-2">
              No boards yet. Make one for a team, a product or a stream of ideas.
            </div>
          )}
          <ul className="grid gap-3 sm:grid-cols-2">
            {boards.data?.map((b) => (
              <li key={b.id}>
                <Link
                  to="/boards/$boardId"
                  params={{ boardId: b.id }}
                  className="block rounded-xl border border-line bg-surface p-4 shadow-card transition hover:border-line-strong"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-[15px] font-semibold">{b.name}</span>
                    {!b.all_access && (
                      <span className="rounded-full bg-surface-2 px-1.5 text-[11px] text-ink-3">restricted</span>
                    )}
                  </div>
                  <div className="mt-2 flex gap-4 text-[12.5px] text-ink-2">
                    <span>
                      <strong className="text-ink">{b.counts.maybe}</strong> in Maybe?
                    </span>
                    <span>
                      <strong className="text-ink">{b.counts.open}</strong> open
                    </span>
                    <span>{b.counts.not_now} not now</span>
                    <span>{b.counts.done} done</span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </section>

        {(pins.data?.length ?? 0) > 0 && (
          <section>
            <h2 className="mb-2 flex items-center gap-1.5 text-[14px] font-semibold">
              <Icon name="pin" size={14} /> Pinned
            </h2>
            <ul className="space-y-1">
              {pins.data?.map((c) => (
                <li key={c.id}>
                  <Link
                    to="/boards/$boardId"
                    params={{ boardId: c.board_id }}
                    search={{ card: c.number }}
                    className="flex items-center gap-2 rounded-md px-2 py-1.5 text-[13.5px] hover:bg-surface-2"
                  >
                    <span className="font-mono text-[11px] text-ink-3">#{c.number}</span>
                    {c.title}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>

      <aside>
        <h2 className="mb-3 text-[14px] font-semibold">Activity</h2>
        {timeline.data && <Timeline events={timeline.data.events} users={timeline.data.users} />}
        {timeline.data?.events.length === 0 && <p className="text-[13px] text-ink-3">Nothing has happened yet.</p>}
      </aside>
    </div>
  );
}

export function Timeline({ events, users }: { events: EventOut[]; users: Record<string, import("../api/client").UserBrief> }) {
  const groups: { key: string; label: string; items: EventOut[] }[] = [];
  for (const e of events) {
    const key = dayKey(e.created_at);
    const last = groups.at(-1);
    if (last?.key === key) last.items.push(e);
    else groups.push({ key, label: dayLabel(e.created_at), items: [e] });
  }
  return (
    <div className="space-y-4">
      {groups.map((g) => (
        <section key={g.key}>
          <h3 className="mb-1.5 text-[11.5px] font-semibold tracking-wide text-ink-3 uppercase">{g.label}</h3>
          <ul className="space-y-1.5">
            {g.items.map((e) => (
              <li key={e.id} className="flex gap-2 text-[12.5px]">
                {e.actor_id ? (
                  <Avatar user={users[e.actor_id]} size={18} />
                ) : (
                  <span className="inline-flex size-[18px] items-center justify-center rounded-full bg-surface-3 text-ink-3">
                    <Icon name="clock" size={11} />
                  </span>
                )}
                <span className="min-w-0 flex-1" title={fullTime(e.created_at)}>
                  {e.card_id && e.card_number != null ? (
                    <Link
                      to="/boards/$boardId"
                      params={{ boardId: e.board_id }}
                      search={{ card: e.card_number }}
                      className="block truncate font-medium text-ink hover:underline"
                    >
                      #{e.card_number} {e.card_title}
                    </Link>
                  ) : null}
                  <span className="block text-ink-2">
                    {describe(e, users, { withCard: !e.card_id })}
                    <span className="text-ink-3"> · {e.board_name}</span>
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function NewBoard() {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  if (!open)
    return (
      <Button variant="primary" onClick={() => setOpen(true)}>
        <Icon name="plus" size={14} /> New board
      </Button>
    );
  return (
    <form
      className="flex gap-2"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!name.trim()) return;
        try {
          const board = await call(
            api.POST("/api/boards", {
              body: {
                name: name.trim(),
                all_access: true,
                columns: [
                  { name: "Doing", color: "blue" },
                  { name: "Review", color: "violet" },
                ],
              },
            }),
          );
          void qc.invalidateQueries({ queryKey: keys.boards });
          void navigate({ to: "/boards/$boardId", params: { boardId: board.id } });
        } catch (err) {
          toast(errorText(err));
        }
      }}
    >
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        placeholder="Board name"
        className="rounded-md border border-line bg-surface px-2.5 py-1.5 text-[13px] outline-none focus:border-accent"
      />
      <Button variant="primary" type="submit">
        Create
      </Button>
    </form>
  );
}
