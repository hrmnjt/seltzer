import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Popover } from "radix-ui";
import { useState } from "react";
import { api, call } from "../api/client";
import { keys, useMe, useNotifications } from "../api/hooks";
import { describe } from "../lib/events";
import { ago } from "../lib/time";
import { Avatar, Icon } from "./ui";

const REASON: Record<string, string> = { mentioned: "Mentioned you", assigned: "Assigned to you", watching: "Watching" };

/** The tray stacks updates per card, so ten edits to one card read as one item. */
export function NotificationTray() {
  const [open, setOpen] = useState(false);
  const me = useMe();
  const inbox = useNotifications(open);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const unread = me.data?.unread_notifications ?? 0;

  async function markRead(cardIds?: string[]) {
    await call(api.POST("/api/notifications/read", { body: { card_ids: cardIds ?? null } }));
    void qc.invalidateQueries({ queryKey: keys.notifications });
    void qc.invalidateQueries({ queryKey: keys.me });
  }

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button
          type="button"
          className="relative rounded-md p-1.5 text-ink-2 hover:bg-surface-2 hover:text-ink"
          aria-label={unread ? `${unread} cards with new activity` : "Notifications"}
        >
          <Icon name="bell" size={18} />
          {unread > 0 && (
            <span className="absolute -top-0.5 -right-0.5 min-w-4 rounded-full bg-accent px-1 text-center text-[10px] leading-4 font-bold text-accent-ink">
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={6}
          className="z-50 flex max-h-[70vh] w-[380px] flex-col rounded-xl border border-line bg-surface shadow-lift"
        >
          <header className="flex items-center justify-between border-b border-line px-3 py-2">
            <span className="text-[13px] font-semibold">Notifications</span>
            {unread > 0 && (
              <button type="button" onClick={() => void markRead()} className="text-[12px] text-accent hover:underline">
                Mark all read
              </button>
            )}
          </header>
          <div className="overflow-y-auto p-1">
            {inbox.isLoading && <p className="p-3 text-[13px] text-ink-3">Loading…</p>}
            {inbox.data?.groups.length === 0 && (
              <p className="p-6 text-center text-[13px] text-ink-3">
                Nothing new. Watch a card or board to hear about it here.
              </p>
            )}
            {inbox.data?.groups.map((g) => (
              <button
                type="button"
                key={g.card_id}
                onClick={() => {
                  setOpen(false);
                  void markRead([g.card_id]);
                  void navigate({ to: "/boards/$boardId", params: { boardId: g.board_id }, search: { card: g.card_number } });
                }}
                className="flex w-full gap-2.5 rounded-lg px-2 py-2 text-left hover:bg-surface-2"
              >
                <span className="flex -space-x-1.5 pt-0.5">
                  {g.actor_ids.slice(0, 2).map((id) => (
                    <Avatar key={id} user={inbox.data.users[id]} size={22} />
                  ))}
                  {g.actor_ids.length === 0 && (
                    <span className="inline-flex size-[22px] items-center justify-center rounded-full bg-surface-3 text-ink-3">
                      <Icon name="clock" size={12} />
                    </span>
                  )}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5">
                    <span className="truncate text-[13px] font-semibold">
                      #{g.card_number} {g.card_title}
                    </span>
                    {g.unread > 0 && <span className="size-2 shrink-0 rounded-full bg-accent" aria-label="unread" />}
                  </span>
                  <span className="block truncate text-[12.5px] text-ink-2">{describe(g.latest, inbox.data.users)}</span>
                  <span className="block text-[11.5px] text-ink-3">
                    {g.board_name} · {ago(g.latest.created_at)}
                    {g.total > 1 && ` · ${g.total} updates`}
                    {g.reasons.includes("mentioned") ? ` · ${REASON.mentioned}` : g.reasons.includes("assigned") ? ` · ${REASON.assigned}` : ""}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
