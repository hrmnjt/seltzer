/**
 * An in-browser stand-in for Seltzer's API, used only by the design-preview build.
 * It follows the backend's lifecycle rules (seltzer/domain) closely enough to click
 * through every screen; nothing leaves the browser and a reload resets it.
 */
import type { RichText, Schemas } from "../api/client";
import { keyBetween } from "../lib/ordering";

type CardTile = Schemas["CardTile"];
type EventOut = Schemas["EventOut"];

export type User = Schemas["UserOut"];
export type Board = {
  id: string;
  name: string;
  all_access: boolean;
  auto_postpone_days: number | null;
  created_by: string;
  archived_at: string | null;
  version: number;
};
export type Column = { id: string; board_id: string; name: string; color: string; position: string };
export type Card = {
  id: string;
  number: number;
  board_id: string;
  column_id: string | null;
  title: string;
  description: RichText | null;
  description_text: string;
  status: "draft" | "published";
  state: "active" | "not_now" | "done";
  state_changed_at: string | null;
  state_changed_by: string | null;
  auto_postponed: boolean;
  golden_at: string | null;
  last_active_at: string;
  created_by: string;
  created_at: string;
  version: number;
};
type Step = Schemas["StepOut"] & { card_id: string };
type Comment = { id: string; card_id: string; author_id: string; body: RichText; body_text: string; created_at: string; edited_at: string | null };
type Reaction = { comment_id: string; user_id: string; emoji: string };
type Event = { id: string; seq: number; board_id: string; card_id: string | null; actor_id: string | null; action: string; details: Record<string, unknown>; created_at: string };
type Notification = { id: string; user_id: string; card_id: string; event_id: string; reason: "watching" | "assigned" | "mentioned"; read_at: string | null };
type Attachment = Schemas["AttachmentOut"] & { card_id: string };

export class Problem extends Error {
  constructor(
    readonly status: number,
    readonly title: string,
    detail: string,
    readonly extra: Record<string, unknown> = {},
  ) {
    super(detail);
  }
}

const NOTIFYING = new Set([
  "published", "triaged", "moved", "sent_back_to_triage", "postponed", "auto_postponed",
  "resumed", "closed", "reopened", "assigned", "commented", "board_changed",
]);
const STAMP_ACTIONS = new Set([
  "published", "triaged", "moved", "sent_back_to_triage", "postponed", "auto_postponed",
  "resumed", "closed", "reopened",
]);
const DAY = 86_400_000;

let idCounter = 0;
export const newId = (prefix: string) => `${prefix}-${(++idCounter).toString(36).padStart(5, "0")}`;

export function plainText(doc: RichText | null | undefined): string {
  const out: string[] = [];
  const walk = (n: { type?: string; text?: string; attrs?: { label?: string }; content?: unknown[] }) => {
    if (n.type === "text") out.push(n.text ?? "");
    else if (n.type === "mention") out.push(`@${n.attrs?.label ?? ""}`);
    for (const c of (n.content ?? []) as (typeof n)[]) walk(c);
    if (n.type && !["text", "mention", "hardBreak", "doc"].includes(n.type)) out.push("\n");
  };
  if (doc) walk(doc as never);
  return out.join("").split("\n").map((l) => l.trim()).filter(Boolean).join("\n");
}

function mentions(doc: RichText | null | undefined): Set<string> {
  const found = new Set<string>();
  const walk = (n: { type?: string; attrs?: { id?: string }; content?: unknown[] }) => {
    if (n.type === "mention" && n.attrs?.id) found.add(n.attrs.id);
    for (const c of (n.content ?? []) as (typeof n)[]) walk(c);
  };
  if (doc) walk(doc as never);
  return found;
}

export class Store {
  users: User[] = [];
  boards: Board[] = [];
  columns: Column[] = [];
  cards: Card[] = [];
  steps: Step[] = [];
  tags: Schemas["TagOut"][] = [];
  cardTags = new Map<string, Set<string>>();
  assignments = new Map<string, string[]>();
  comments: Comment[] = [];
  reactions: Reaction[] = [];
  events: Event[] = [];
  watches = new Set<string>();
  boardWatches = new Set<string>();
  access = new Map<string, Set<string>>();
  pins: { user_id: string; card_id: string; position: string }[] = [];
  notifications: Notification[] = [];
  attachments: Attachment[] = [];
  settings = { default_auto_postpone_days: 30 };
  nextNumber = 1;
  seq = 0;

  /** Who is acting, and when. The seed moves both; the live demo is always "me, now". */
  actor = "";
  me = "";
  clock: () => number = () => Date.now();

  now() {
    return new Date(this.clock()).toISOString();
  }

  // Lookups and permissions ---------------------------------------------------------

  user(id: string) {
    return this.users.find((u) => u.id === id);
  }
  isAdmin(uid = this.me) {
    const r = this.user(uid)?.role;
    return r === "owner" || r === "admin";
  }
  canSee(board: Board, uid = this.me) {
    return board.all_access || this.isAdmin(uid) || board.created_by === uid || !!this.access.get(board.id)?.has(uid);
  }
  canAdmin(board: Board, uid = this.me) {
    return this.isAdmin(uid) || board.created_by === uid;
  }
  board(id: string, opts: { admin?: boolean } = {}) {
    const b = this.boards.find((x) => x.id === id);
    if (!b || !this.canSee(b)) throw new Problem(404, "Not found", "No such board");
    if (opts.admin && !this.canAdmin(b)) throw new Problem(403, "Not allowed", "Only the board's creator or an admin can change this");
    return b;
  }
  card(number: number) {
    const c = this.cards.find((x) => x.number === number);
    if (!c || (c.status === "draft" && c.created_by !== this.me)) throw new Problem(404, "Not found", `No card #${number}`);
    this.board(c.board_id);
    return c;
  }
  period(board: Board) {
    return board.auto_postpone_days ?? this.settings.default_auto_postpone_days;
  }
  bump(boardId: string) {
    const b = this.boards.find((x) => x.id === boardId);
    if (b) b.version += 1;
  }

  // Events and notifications ---------------------------------------------------------

  record(action: string, boardId: string, card: Card | null, details: Record<string, unknown> = {}, opts: { touch?: boolean; mentions?: Set<string>; assignee?: string } = {}) {
    const ev: Event = {
      id: newId("ev"),
      seq: ++this.seq,
      board_id: boardId,
      card_id: card?.id ?? null,
      actor_id: this.actor || null,
      action,
      details,
      created_at: this.now(),
    };
    this.events.push(ev);
    if (card && opts.touch !== false) card.last_active_at = ev.created_at;
    this.bump(boardId);
    if (card?.status === "published") this.notify(ev, card, opts.mentions ?? new Set(), opts.assignee);
    return ev;
  }

  private notify(ev: Event, card: Card, mentioned: Set<string>, assignee?: string) {
    const reasons = new Map<string, Notification["reason"]>();
    if (NOTIFYING.has(ev.action)) {
      for (const key of this.watches) if (key.startsWith(`${card.id}:`)) reasons.set(key.split(":")[1]!, "watching");
      for (const key of this.boardWatches) if (key.startsWith(`${card.board_id}:`)) reasons.set(key.split(":")[1]!, "watching");
      for (const uid of this.assignments.get(card.id) ?? []) reasons.set(uid, "assigned");
    }
    if (assignee) reasons.set(assignee, "assigned");
    for (const uid of mentioned) reasons.set(uid, "mentioned");
    if (ev.actor_id) reasons.delete(ev.actor_id);
    const board = this.boards.find((b) => b.id === card.board_id)!;
    for (const [uid, reason] of reasons) {
      if (!this.user(uid)?.active || !this.canSee(board, uid)) continue;
      this.notifications.push({ id: newId("nt"), user_id: uid, card_id: card.id, event_id: ev.id, reason, read_at: null });
    }
  }

  watch(cardId: string, uid: string) {
    this.watches.add(`${cardId}:${uid}`);
  }

  // Ordering ----------------------------------------------------------------------------

  /** Mirrors domain/positions.place(): always between two adjacent items. */
  place<T extends { position: string }>(items: T[], self: T | null, key: (t: T) => string, above?: string | null, below?: string | null, top = true) {
    const others = items.filter((i) => i !== self).sort((a, b) => (a.position < b.position ? -1 : 1));
    const lo = above ? others.find((i) => key(i) === above)?.position : undefined;
    if (lo !== undefined) return keyBetween(lo, others.find((i) => i.position > lo)?.position ?? null);
    const hi = below ? others.find((i) => key(i) === below)?.position : undefined;
    if (hi !== undefined) return keyBetween([...others].reverse().find((i) => i.position < hi)?.position ?? null, hi);
    return top ? keyBetween(null, others[0]?.position ?? null) : keyBetween(others.at(-1)?.position ?? null, null);
  }

  // Boards and columns --------------------------------------------------------------------

  createBoard(name: string, allAccess: boolean, period: number | null, columns: { name: string; color: string }[]) {
    const b: Board = { id: newId("board"), name: name.trim(), all_access: allAccess, auto_postpone_days: period, created_by: this.actor, archived_at: null, version: 1 };
    this.boards.push(b);
    this.boardWatches.add(`${b.id}:${this.actor}`);
    for (const c of columns) this.addColumn(b, c.name, c.color);
    return b;
  }

  addColumn(board: Board, name: string, color: string, above?: string | null, below?: string | null) {
    const cols = this.columns.filter((c) => c.board_id === board.id);
    const col: Column = { id: newId("col"), board_id: board.id, name: name.trim(), color, position: "V" };
    col.position = this.place(cols, null, (c) => c.id, above, below, false);
    this.columns.push(col);
    this.bump(board.id);
    return col;
  }

  // Cards: the lifecycle -----------------------------------------------------------------

  createCard(board: Board, title: string, opts: { description?: RichText | null; draft?: boolean } = {}) {
    const text = title.split(/\s+/).join(" ").trim();
    if (!text) throw new Problem(422, "Invalid request", "A card needs a title");
    const now = this.now();
    const card: Card = {
      id: newId("card"),
      number: this.nextNumber++,
      board_id: board.id,
      column_id: null,
      title: text,
      description: opts.description ?? null,
      description_text: plainText(opts.description),
      status: opts.draft ? "draft" : "published",
      state: "active",
      state_changed_at: null,
      state_changed_by: null,
      auto_postponed: false,
      golden_at: null,
      last_active_at: now,
      created_by: this.actor,
      created_at: now,
      version: 1,
    };
    this.cards.push(card);
    this.watch(card.id, this.actor);
    if (!opts.draft) this.publish(card);
    else this.bump(board.id);
    return card;
  }

  publish(card: Card) {
    card.status = "published";
    card.column_id = null;
    this.record("published", card.board_id, card, {}, { mentions: mentions(card.description) });
  }

  private setState(card: Card, state: Card["state"], auto = false) {
    card.state = state;
    card.state_changed_at = this.now();
    card.state_changed_by = auto ? null : this.actor;
    card.auto_postponed = auto;
  }

  private requirePublished(card: Card) {
    if (card.status !== "published") throw new Problem(409, "Conflict", "Publish this draft first");
  }

  // Cards are never placed by hand: a lane lists golden cards first, then the most
  // recently active, and every move touches the card, so it lands on top.

  triage(card: Card, columnId: string) {
    this.requirePublished(card);
    const column = this.columns.find((c) => c.id === columnId && c.board_id === card.board_id);
    if (!column) throw new Problem(404, "Not found", "No such column on this board");
    if (card.state === "active" && card.column_id === column.id)
      throw new Problem(409, "Conflict", "The card is already in this column", { current: card.state });
    let previous = card.column_id;
    if (card.state === "not_now") {
      this.setState(card, "active");
      card.column_id = null;
      this.record("resumed", card.board_id, card);
      previous = null;
    } else if (card.state === "done") {
      this.setState(card, "active");
      this.record("reopened", card.board_id, card);
    }
    card.column_id = column.id;
    if (previous === null) this.record("triaged", card.board_id, card, { column_id: column.id, column: column.name });
    else if (previous !== column.id) {
      const old = this.columns.find((c) => c.id === previous);
      this.record("moved", card.board_id, card, { from_column: old?.name ?? null, column: column.name, column_id: column.id });
    }
  }

  /** To Maybe?, from a column, Not Now or Done. */
  untriage(card: Card) {
    this.requirePublished(card);
    if (card.state === "not_now") return this.resume(card);
    if (card.state === "active" && !card.column_id)
      throw new Problem(409, "Conflict", "The card is already in Maybe?", { current: card.state });
    if (card.state === "done") {
      this.setState(card, "active");
      this.record("reopened", card.board_id, card);
      if (!card.column_id) return;
    }
    const old = this.columns.find((c) => c.id === card.column_id);
    card.column_id = null;
    this.record("sent_back_to_triage", card.board_id, card, { from_column: old?.name ?? null });
  }

  /** To Not Now, from Maybe?, a column or Done. */
  postpone(card: Card, auto = false) {
    this.requirePublished(card);
    if (card.state === "not_now") throw new Problem(409, "Conflict", "This card is already in Not Now", { current: card.state });
    this.setState(card, "not_now", auto);
    card.column_id = null;
    this.record(auto ? "auto_postponed" : "postponed", card.board_id, card);
  }

  resume(card: Card) {
    this.requirePublished(card);
    if (card.state !== "not_now") throw new Problem(409, "Conflict", "Only cards in Not Now can be resumed", { current: card.state });
    this.setState(card, "active");
    card.column_id = null;
    this.record("resumed", card.board_id, card);
  }

  close(card: Card) {
    this.requirePublished(card);
    if (card.state === "done") throw new Problem(409, "Conflict", "This card is already done", { current: card.state });
    this.setState(card, "done");
    this.record("closed", card.board_id, card);
  }

  reopen(card: Card) {
    this.requirePublished(card);
    if (card.state !== "done") throw new Problem(409, "Conflict", "Only done cards can be reopened", { current: card.state });
    this.setState(card, "active");
    if (card.column_id && !this.columns.some((c) => c.id === card.column_id)) card.column_id = null;
    this.record("reopened", card.board_id, card);
  }

  gild(card: Card, on: boolean) {
    this.requirePublished(card);
    if (on === !!card.golden_at) return;
    card.golden_at = on ? this.now() : null;
    this.record(on ? "gilded" : "ungilded", card.board_id, card);
  }

  edit(card: Card, patch: { title?: string; description?: RichText | null; board_id?: string; version?: number | null }, fields: Set<string>) {
    if (patch.version != null && patch.version !== card.version)
      throw new Problem(409, "Conflict", "This card changed since you opened it", { current_version: card.version });
    let changed = false;
    if (fields.has("title") && patch.title != null) {
      const t = patch.title.split(/\s+/).join(" ").trim();
      if (!t) throw new Problem(422, "Invalid request", "A card needs a title");
      if (t !== card.title) {
        const from = card.title;
        card.title = t;
        changed = true;
        if (card.status === "published") this.record("title_changed", card.board_id, card, { from, to: t });
      }
    }
    if (fields.has("description")) {
      const doc = patch.description ?? null;
      if (JSON.stringify(doc) !== JSON.stringify(card.description)) {
        const before = mentions(card.description);
        card.description = doc;
        card.description_text = plainText(doc);
        changed = true;
        if (card.status === "published") {
          const fresh = new Set([...mentions(doc)].filter((m) => !before.has(m)));
          this.record("description_changed", card.board_id, card, {}, { mentions: fresh });
        }
      }
    }
    if (fields.has("board_id") && patch.board_id && patch.board_id !== card.board_id) {
      const source = this.board(card.board_id);
      const target = this.board(patch.board_id);
      this.bump(source.id);
      card.board_id = target.id;
      card.column_id = null;
      if (card.status === "published") this.record("board_changed", target.id, card, { from_board: source.name });
      changed = true;
    }
    if (changed) card.version += 1;
  }

  tag(card: Card, tagId: string, on: boolean) {
    const tag = this.tags.find((t) => t.id === tagId);
    if (!tag) throw new Problem(404, "Not found", "No such tag");
    const set = this.cardTags.get(card.id) ?? new Set<string>();
    if (on === set.has(tagId)) return;
    if (on) set.add(tagId);
    else set.delete(tagId);
    this.cardTags.set(card.id, set);
    if (card.status === "published") this.record(on ? "tagged" : "untagged", card.board_id, card, { tag: tag.name });
  }

  assign(card: Card, userId: string, on: boolean) {
    const user = this.user(userId);
    if (!user) throw new Problem(404, "Not found", "No such person");
    const list = this.assignments.get(card.id) ?? [];
    if (on === list.includes(userId)) return;
    if (on && !this.canSee(this.boards.find((b) => b.id === card.board_id)!, userId))
      throw new Problem(422, "Invalid request", `${user.display_name} can't see this board`);
    this.assignments.set(card.id, on ? [...list, userId] : list.filter((u) => u !== userId));
    if (card.status === "published")
      this.record(on ? "assigned" : "unassigned", card.board_id, card, { name: user.display_name }, on ? { assignee: userId } : {});
  }

  addStep(card: Card, body: string, completed = false) {
    const text = body.trim();
    if (!text) throw new Problem(422, "Invalid request", "Steps need 1 to 500 characters");
    const siblings = this.steps.filter((s) => s.card_id === card.id);
    const step: Step = { id: newId("step"), card_id: card.id, body: text, position: this.place(siblings, null, (s) => s.id, null, null, false), completed_at: null, completed_by: null };
    this.steps.push(step);
    if (card.status === "published") this.record("step_added", card.board_id, card, { step: text });
    if (completed) this.completeStep(step, card, true);
    return step;
  }

  completeStep(step: Step, card: Card, done: boolean) {
    if (done === !!step.completed_at) return;
    step.completed_at = done ? this.now() : null;
    step.completed_by = done ? this.actor : null;
    if (card.status === "published") this.record(done ? "step_completed" : "step_uncompleted", card.board_id, card, { step: step.body });
  }

  comment(card: Card, body: RichText) {
    const text = plainText(body);
    if (!text) throw new Problem(422, "Invalid request", "A comment can't be empty");
    const c: Comment = { id: newId("cm"), card_id: card.id, author_id: this.actor, body, body_text: text, created_at: this.now(), edited_at: null };
    this.comments.push(c);
    this.watch(card.id, this.actor);
    if (card.status === "published") this.record("commented", card.board_id, card, { excerpt: text.slice(0, 140) }, { mentions: mentions(body) });
    return c;
  }

  react(commentId: string, emoji: string, on: boolean) {
    const has = this.reactions.some((r) => r.comment_id === commentId && r.user_id === this.actor && r.emoji === emoji);
    if (on && !has) this.reactions.push({ comment_id: commentId, user_id: this.actor, emoji });
    if (!on) this.reactions = this.reactions.filter((r) => !(r.comment_id === commentId && r.user_id === this.actor && r.emoji === emoji));
  }

  /** Auto-postpone, as the hourly job would. */
  sweep() {
    const now = this.clock();
    let n = 0;
    for (const card of this.cards) {
      const board = this.boards.find((b) => b.id === card.board_id)!;
      if (card.status !== "published" || card.state !== "active" || board.archived_at) continue;
      if (now - Date.parse(card.last_active_at) > this.period(board) * DAY) {
        const actor = this.actor;
        this.actor = "";
        this.postpone(card, true);
        this.actor = actor;
        n++;
      }
    }
    return n;
  }

  // Read models ---------------------------------------------------------------------------

  tile(c: Card): CardTile {
    const board = this.boards.find((b) => b.id === c.board_id)!;
    const steps = this.steps.filter((s) => s.card_id === c.id);
    const stamp = [...this.events].reverse().find((e) => e.card_id === c.id && STAMP_ACTIONS.has(e.action));
    let postponeAt: string | null = null;
    let closingSoon = false;
    if (c.status === "published" && c.state === "active") {
      const period = this.period(board) * DAY;
      const last = Date.parse(c.last_active_at);
      postponeAt = new Date(last + period).toISOString();
      closingSoon = this.clock() >= last + period * 0.75;
    }
    return {
      id: c.id,
      number: c.number,
      title: c.title,
      board_id: c.board_id,
      column_id: c.column_id,
      status: c.status,
      state: c.state,
      golden: !!c.golden_at,
      auto_postponed: c.auto_postponed,
      tags: this.tags.filter((t) => this.cardTags.get(c.id)?.has(t.id)).sort((a, b) => a.name.localeCompare(b.name)),
      assignee_ids: this.assignments.get(c.id) ?? [],
      steps_total: steps.length,
      steps_done: steps.filter((s) => s.completed_at).length,
      comments_count: this.comments.filter((m) => m.card_id === c.id).length,
      attachments_count: this.attachments.filter((a) => a.card_id === c.id).length,
      created_by: c.created_by,
      created_at: c.created_at,
      last_active_at: c.last_active_at,
      state_changed_at: c.state_changed_at,
      state_changed_by: c.state_changed_by,
      auto_postpone_at: postponeAt,
      closing_soon: closingSoon,
      stamp: stamp ? { action: stamp.action, actor_id: stamp.actor_id, at: stamp.created_at } : null,
      version: c.version,
    };
  }

  usersMap() {
    return Object.fromEntries(this.users.map((u) => [u.id, { id: u.id, display_name: u.display_name, email: u.email }]));
  }

  summary(b: Board): Schemas["BoardSummary"] {
    const pub = this.cards.filter((c) => c.board_id === b.id && c.status === "published");
    const open = pub.filter((c) => c.state === "active");
    return {
      id: b.id,
      name: b.name,
      all_access: b.all_access,
      auto_postpone_days: b.auto_postpone_days,
      effective_auto_postpone_days: this.period(b),
      archived_at: b.archived_at,
      created_by: b.created_by,
      can_admin: this.canAdmin(b),
      watching: this.boardWatches.has(`${b.id}:${this.me}`),
      counts: {
        maybe: open.filter((c) => !c.column_id).length,
        open: open.length,
        not_now: pub.filter((c) => c.state === "not_now").length,
        done: pub.filter((c) => c.state === "done").length,
      },
      version: b.version,
    };
  }

  eventOut(e: Event): EventOut {
    const card = e.card_id ? this.cards.find((c) => c.id === e.card_id) : undefined;
    return {
      id: e.id,
      board_id: e.board_id,
      board_name: this.boards.find((b) => b.id === e.board_id)?.name ?? null,
      card_id: card ? e.card_id : null,
      card_number: card?.number ?? (e.details.number as number | undefined) ?? null,
      card_title: card?.title ?? (e.details.title as string | undefined) ?? null,
      actor_id: e.actor_id,
      action: e.action,
      details: e.details,
      created_at: e.created_at,
    };
  }

  detail(c: Card): Schemas["CardDetail"] {
    const board = this.boards.find((b) => b.id === c.board_id)!;
    return {
      card: this.tile(c),
      description: c.description,
      board_name: board.name,
      column_name: this.columns.find((col) => col.id === c.column_id)?.name ?? null,
      steps: this.steps.filter((s) => s.card_id === c.id).sort((a, b) => (a.position < b.position ? -1 : 1)),
      comments: this.comments
        .filter((m) => m.card_id === c.id)
        .map((m) => {
          const byEmoji = new Map<string, string[]>();
          for (const r of this.reactions.filter((r) => r.comment_id === m.id)) byEmoji.set(r.emoji, [...(byEmoji.get(r.emoji) ?? []), r.user_id]);
          return {
            id: m.id,
            card_id: m.card_id,
            author_id: m.author_id,
            body: m.body,
            created_at: m.created_at,
            edited_at: m.edited_at,
            reactions: [...byEmoji].map(([emoji, ids]) => ({ emoji, count: ids.length, user_ids: ids, mine: ids.includes(this.me) })),
          };
        }),
      attachments: this.attachments.filter((a) => a.card_id === c.id),
      events: this.events.filter((e) => e.card_id === c.id).reverse().slice(0, 100).map((e) => this.eventOut(e)),
      watching: this.watches.has(`${c.id}:${this.me}`),
      pinned: this.pins.some((p) => p.user_id === this.me && p.card_id === c.id),
      can_delete: c.created_by === this.me || this.canAdmin(board),
      users: this.usersMap(),
    };
  }
}
