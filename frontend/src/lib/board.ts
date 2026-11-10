import type { BoardSnapshot, CardTile } from "../api/client";

/** Lane ids for the board canvas: Not Now, Maybe?, each column's id, and Done. */
export const MAYBE = "lane:maybe";
export const NOT_NOW = "lane:not_now";
export const DONE = "lane:done";

export type LaneId = string; // MAYBE or a column id

/** The server's lane order: golden cards first, then the most recently active. */
export function byLaneOrder(a: CardTile, b: CardTile): number {
  if (a.golden !== b.golden) return a.golden ? -1 : 1;
  if (a.last_active_at !== b.last_active_at) return a.last_active_at > b.last_active_at ? -1 : 1;
  return a.id > b.id ? -1 : a.id < b.id ? 1 : 0;
}

export type Filters = {
  view?: "open" | "golden" | "closing_soon";
  tag?: string;
  assignee?: string;
};

export function matches(card: CardTile, f: Filters): boolean {
  if (f.view === "golden" && !card.golden) return false;
  if (f.view === "closing_soon" && !card.closing_soon) return false;
  if (f.tag && !card.tags.some((t) => t.id === f.tag)) return false;
  if (f.assignee && !card.assignee_ids.includes(f.assignee)) return false;
  return true;
}

/** Card ids per lane, in display order. */
export function lanesOf(snap: BoardSnapshot, f: Filters = {}): Record<LaneId, string[]> {
  const lanes: Record<LaneId, string[]> = { [MAYBE]: [] };
  for (const col of snap.columns) lanes[col.id] = [];
  const sorted = snap.cards.filter((c) => matches(c, f)).sort(byLaneOrder);
  for (const card of sorted) {
    const lane = card.column_id ?? MAYBE;
    (lanes[lane] ??= []).push(card.id);
  }
  return lanes;
}

export const ACTION_LABELS: Record<string, string> = {
  published: "Filed",
  triaged: "Triaged",
  moved: "Moved",
  sent_back_to_triage: "Sent back",
  postponed: "Postponed",
  auto_postponed: "Auto-postponed",
  resumed: "Resumed",
  closed: "Closed",
  reopened: "Reopened",
  gilded: "Gilded",
  ungilded: "Ungilded",
  assigned: "Assigned",
  unassigned: "Unassigned",
  tagged: "Tagged",
  untagged: "Untagged",
  title_changed: "Renamed",
  description_changed: "Edited",
  board_changed: "Moved board",
  commented: "Commented",
  step_added: "Added step",
  step_completed: "Checked off",
  step_uncompleted: "Unchecked",
  attached: "Attached",
  deleted: "Deleted",
};
