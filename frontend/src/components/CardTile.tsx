import type { CardTile as Tile, UsersMap } from "../api/client";
import { colorVar } from "../api/client";
import { ACTION_LABELS } from "../lib/board";
import { ago, daysUntil } from "../lib/time";
import { Avatar, Icon } from "./ui";

export function Stamp({ tile, users }: { tile: Tile; users: UsersMap }) {
  const stamp = tile.stamp;
  if (!stamp) return null;
  const who = stamp.actor_id ? users[stamp.actor_id]?.display_name.split(" ")[0] : "Seltzer";
  return (
    <span className="truncate text-[11px] text-ink-3" title={`${ACTION_LABELS[stamp.action] ?? stamp.action} by ${who}`}>
      {ACTION_LABELS[stamp.action] ?? stamp.action} by {who} · {ago(stamp.at)}
    </span>
  );
}

type Props = {
  tile: Tile;
  users: UsersMap;
  onOpen: (number: number) => void;
  dragging?: boolean;
  overlay?: boolean;
  accent?: string;
};

export function CardTileView({ tile, users, onOpen, dragging, overlay, accent }: Props) {
  const closingIn = tile.auto_postpone_at ? daysUntil(tile.auto_postpone_at) : null;
  return (
    <div
      className={`group relative rounded-lg border bg-surface px-2.5 py-2 text-left shadow-card transition ${
        tile.golden ? "border-gold" : "border-line"
      } ${dragging ? "opacity-30" : ""} ${overlay ? "rotate-1 shadow-lift" : "hover:border-line-strong"} ${
        tile.closing_soon ? "opacity-70" : ""
      }`}
      style={tile.golden ? { background: "linear-gradient(var(--gold-soft), var(--surface) 70%)" } : undefined}
    >
      {accent && (
        <span className="absolute top-2 bottom-2 left-0 w-[3px] rounded-r" style={{ background: colorVar(accent) }} />
      )}
      <button
        type="button"
        onClick={() => onOpen(tile.number)}
        className="block w-full text-left"
        aria-label={`Open card ${tile.number}: ${tile.title}`}
      >
        <div className="flex items-start gap-1.5">
          <span className="mt-[1px] font-mono text-[11px] text-ink-3">#{tile.number}</span>
          <span className="min-w-0 flex-1 text-[13.5px] leading-snug font-medium break-words text-ink">
            {tile.title}
          </span>
          {tile.golden && <Icon name="star" size={14} className="mt-[1px] text-gold" />}
        </div>
        {tile.tags.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {tile.tags.map((t) => (
              <span
                key={t.id}
                className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-1.5 py-[1px] text-[11px] text-ink-2"
              >
                <span className="size-1.5 rounded-full" style={{ background: colorVar(t.color) }} />
                {t.name}
              </span>
            ))}
          </div>
        )}
        <div className="mt-1.5 flex items-center gap-2">
          <Stamp tile={tile} users={users} />
          <span className="flex-1" />
          {tile.steps_total > 0 && (
            <span className="inline-flex items-center gap-0.5 text-[11px] text-ink-3" title="Steps">
              <Icon name="check" size={12} />
              {tile.steps_done}/{tile.steps_total}
            </span>
          )}
          {tile.comments_count > 0 && (
            <span className="inline-flex items-center gap-0.5 text-[11px] text-ink-3" title="Comments">
              <Icon name="chat" size={12} />
              {tile.comments_count}
            </span>
          )}
          {tile.assignee_ids.length > 0 && (
            <span className="flex -space-x-1">
              {tile.assignee_ids.slice(0, 3).map((id) => (
                <Avatar key={id} user={users[id]} size={18} />
              ))}
            </span>
          )}
        </div>
        {tile.closing_soon && closingIn != null && (
          <div className="mt-1.5 flex items-center gap-1 text-[11px] font-medium text-ink-2">
            <Icon name="clock" size={12} />
            {closingIn === 0 ? "Moves to Not Now soon" : `Moves to Not Now in ${closingIn}d`}
          </div>
        )}
      </button>
    </div>
  );
}
