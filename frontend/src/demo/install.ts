/**
 * Design-preview only: answers /api/* requests from the in-browser Store instead of the
 * network. Imported before the app so the API client picks up the patched fetch.
 */
import type { RichText } from "../api/client";
import { seed } from "./seed";
import { type Card, newId, plainText, Problem, Store } from "./store";

const store = new Store();
seed(store);

// First visit: open "Building" next to Maybe? so the two-lane layout shows straight away.
try {
  const platform = store.boards.find((b) => b.name === "Platform");
  const building = store.columns.find((c) => c.board_id === platform?.id && c.name === "Building");
  const key = `seltzer:open-lane:${platform?.id}`;
  if (platform && building && !sessionStorage.getItem("seltzer:preview-opened")) {
    localStorage.setItem(key, building.id);
    sessionStorage.setItem("seltzer:preview-opened", "1");
  }
} catch {
  /* storage can be unavailable */
}

type Handler = (m: string[], q: URLSearchParams, body: Record<string, unknown>, req: Request) => unknown | Promise<unknown>;
const routes: [string, RegExp, Handler][] = [];
const on = (method: string, pattern: string, handler: Handler) =>
  routes.push([method, new RegExp(`^/api${pattern.replace(/:\w+/g, "([^/]+)")}$`), handler]);

const NO_CONTENT = Symbol("204");
const cardRes = (c: Card) => ({ card: store.tile(c), users: store.usersMap() });
const num = (s: string) => Number(s);
const write = <T,>(fn: () => T) => fn(); // every request acts as the signed-in person (set below)

// People, settings, tags ------------------------------------------------------------------
on("GET", "/me", () => ({
  user: store.user(store.me),
  unread_notifications: new Set(store.notifications.filter((n) => n.user_id === store.me && !n.read_at).map((n) => n.card_id)).size,
  workspace_default_auto_postpone_days: store.settings.default_auto_postpone_days,
}));
on("GET", "/users", (_m, q) => store.users.filter((u) => u.active || q.get("include_inactive") === "true"));
on("PATCH", "/users/:id", ([id], _q, b) => {
  const u = store.user(id!);
  if (!u) throw new Problem(404, "Not found", "No such person");
  if (!store.isAdmin()) throw new Problem(403, "Not allowed", "Only admins can manage people");
  if ((u.role === "owner" || b.role === "owner") && store.user(store.me)?.role !== "owner")
    throw new Problem(403, "Not allowed", "Only owners can grant or change the owner role");
  const losingOwner = u.role === "owner" && ((b.role && b.role !== "owner") || b.active === false);
  if (losingOwner && !store.users.some((x) => x.id !== u.id && x.role === "owner" && x.active))
    throw new Problem(409, "Conflict", "Seltzer needs at least one active owner");
  if (b.role) u.role = b.role as typeof u.role;
  if (typeof b.active === "boolean") u.active = b.active;
  return u;
});
on("GET", "/settings", () => store.settings);
on("PATCH", "/settings", (_m, _q, b) => {
  store.settings.default_auto_postpone_days = Number(b.default_auto_postpone_days);
  store.boards.forEach((x) => store.bump(x.id));
  return store.settings;
});
on("GET", "/tags", () => [...store.tags].sort((a, b) => a.name.localeCompare(b.name)));
on("POST", "/tags", (_m, _q, b) => {
  const name = String(b.name ?? "").trim().replace(/^#/, "");
  const existing = store.tags.find((t) => t.name.toLowerCase() === name.toLowerCase());
  if (existing) return existing;
  const tag = { id: newId("tag"), name, color: String(b.color ?? "gray") };
  store.tags.push(tag);
  return tag;
});

// Boards and columns -----------------------------------------------------------------------
on("GET", "/boards", () =>
  store.boards.filter((b) => store.canSee(b) && !b.archived_at).sort((a, b) => a.name.localeCompare(b.name)).map((b) => store.summary(b)),
);
on("POST", "/boards", (_m, _q, b) =>
  write(() => store.summary(store.createBoard(String(b.name), b.all_access !== false, (b.auto_postpone_days as number) ?? null, (b.columns as { name: string; color: string }[]) ?? []))),
);
on("GET", "/boards/:id", ([id], q) => {
  const b = store.board(id!);
  if (q.get("since") && Number(q.get("since")) === b.version) return NO_CONTENT;
  const cards = store.cards.filter((c) => c.board_id === b.id && c.status === "published" && c.state === "active");
  const drafts = store.cards.filter((c) => c.board_id === b.id && c.status === "draft" && c.created_by === store.me);
  return {
    board: store.summary(b),
    columns: store.columns.filter((c) => c.board_id === b.id).sort((x, y) => (x.position < y.position ? -1 : 1)),
    cards: cards.map((c) => store.tile(c)),
    drafts: drafts.map((c) => store.tile(c)),
    users: store.usersMap(),
    tags: [...store.tags].sort((x, y) => x.name.localeCompare(y.name)),
    version: b.version,
  };
});
on("PATCH", "/boards/:id", ([id], _q, body) => {
  const b = store.board(id!, { admin: true });
  if (typeof body.name === "string" && body.name.trim()) b.name = body.name.trim();
  if (typeof body.all_access === "boolean") b.all_access = body.all_access;
  if ("auto_postpone_days" in body) b.auto_postpone_days = (body.auto_postpone_days as number | null) ?? null;
  if (typeof body.archived === "boolean") b.archived_at = body.archived ? store.now() : null;
  store.bump(b.id);
  return store.summary(b);
});
on("GET", "/boards/:id/access", ([id]) => ({ user_ids: [...(store.access.get(store.board(id!).id) ?? [])] }));
on("PUT", "/boards/:id/access", ([id], _q, body) => {
  const b = store.board(id!, { admin: true });
  store.access.set(b.id, new Set(body.user_ids as string[]));
  store.bump(b.id);
  return { user_ids: body.user_ids };
});
on("PUT", "/boards/:id/watch", ([id]) => {
  store.boardWatches.add(`${store.board(id!).id}:${store.me}`);
  return NO_CONTENT;
});
on("DELETE", "/boards/:id/watch", ([id]) => {
  store.boardWatches.delete(`${store.board(id!).id}:${store.me}`);
  return NO_CONTENT;
});
on("POST", "/boards/:id/columns", ([id], _q, b) =>
  store.addColumn(store.board(id!, { admin: true }), String(b.name), String(b.color ?? "gray"), b.above as string, b.below as string),
);
const column = (id: string) => {
  const c = store.columns.find((x) => x.id === id);
  if (!c) throw new Problem(404, "Not found", "No such column");
  store.board(c.board_id, { admin: true });
  return c;
};
on("PATCH", "/columns/:id", ([id], _q, b) => {
  const c = column(id!);
  if (typeof b.name === "string" && b.name.trim()) c.name = b.name.trim();
  if (typeof b.color === "string") c.color = b.color;
  if (b.above || b.below)
    c.position = store.place(store.columns.filter((x) => x.board_id === c.board_id), c, (x) => x.id, b.above as string, b.below as string);
  store.bump(c.board_id);
  return c;
});
on("DELETE", "/columns/:id", ([id]) => {
  const c = column(id!);
  for (const card of store.cards) if (card.column_id === c.id && card.state === "active") card.column_id = null;
  store.columns = store.columns.filter((x) => x !== c);
  store.bump(c.board_id);
  return NO_CONTENT;
});

// Cards --------------------------------------------------------------------------------------
on("GET", "/boards/:id/cards", ([id], q) => {
  const b = store.board(id!);
  const view = q.get("view") ?? "open";
  let list = store.cards.filter((c) => c.board_id === b.id && (c.status === "published" || c.created_by === store.me));
  const pub = (c: Card) => c.status === "published";
  const filters: Record<string, (c: Card) => boolean> = {
    open: (c) => pub(c) && c.state === "active",
    maybe: (c) => pub(c) && c.state === "active" && !c.column_id,
    not_now: (c) => pub(c) && c.state === "not_now",
    done: (c) => pub(c) && c.state === "done",
    golden: (c) => pub(c) && !!c.golden_at && c.state !== "done",
    closing_soon: (c) => pub(c) && store.tile(c).closing_soon,
    drafts: (c) => c.status === "draft",
  };
  list = list.filter(filters[view] ?? filters.open!);
  const tag = q.get("tag");
  const assignee = q.get("assignee");
  if (tag) list = list.filter((c) => store.cardTags.get(c.id)?.has(tag));
  if (assignee) list = list.filter((c) => store.assignments.get(c.id)?.includes(assignee));
  const sort = q.get("sort") ?? (view === "not_now" || view === "done" ? "changed" : "newest");
  const key = (c: Card) =>
    sort === "activity" ? c.last_active_at : sort === "changed" ? (c.state_changed_at ?? c.created_at) : c.created_at;
  list.sort((a, c) => (key(a) < key(c) ? 1 : -1));
  if (sort === "oldest") list.reverse();
  return { cards: list.slice(0, Number(q.get("limit") ?? 50)).map((c) => store.tile(c)), users: store.usersMap(), next_cursor: null };
});
on("POST", "/boards/:id/cards", ([id], _q, b) =>
  write(() => cardRes(store.createCard(store.board(id!), String(b.title ?? ""), { description: b.description as RichText | null, draft: !!b.draft }))),
);
on("GET", "/cards/:n", ([n]) => store.detail(store.card(num(n!))));
on("PATCH", "/cards/:n", ([n], _q, b) =>
  write(() => {
    const c = store.card(num(n!));
    store.edit(c, b as never, new Set(Object.keys(b)));
    return cardRes(c);
  }),
);
on("DELETE", "/cards/:n", ([n]) =>
  write(() => {
    const c = store.card(num(n!));
    if (c.status === "published") store.record("deleted", c.board_id, c, { number: c.number, title: c.title }, { touch: false });
    else store.bump(c.board_id);
    store.cards = store.cards.filter((x) => x !== c);
    store.notifications = store.notifications.filter((x) => x.card_id !== c.id);
    return NO_CONTENT;
  }),
);
const act = (fn: (c: Card, b: Record<string, unknown>, m: string[]) => void): Handler => (m, _q, b) => {
  const c = store.card(num(m[0]!));
  fn(c, b, m);
  return cardRes(c);
};
on("POST", "/cards/:n/publish", act((c) => {
  if (c.status !== "draft") throw new Problem(409, "Conflict", "This card is already published");
  store.publish(c);
}));
on("POST", "/cards/:n/triage", act((c, b) => store.triage(c, String(b.column_id))));
on("POST", "/cards/:n/untriage", act((c) => store.untriage(c)));
on("POST", "/cards/:n/postpone", act((c) => store.postpone(c)));
on("POST", "/cards/:n/resume", act((c) => store.resume(c)));
on("POST", "/cards/:n/close", act((c) => store.close(c)));
on("POST", "/cards/:n/reopen", act((c) => store.reopen(c)));
on("PUT", "/cards/:n/golden", act((c) => store.gild(c, true)));
on("DELETE", "/cards/:n/golden", act((c) => store.gild(c, false)));
on("PUT", "/cards/:n/tags/:tag", act((c, _b, m) => store.tag(c, m[1]!, true)));
on("DELETE", "/cards/:n/tags/:tag", act((c, _b, m) => store.tag(c, m[1]!, false)));
on("PUT", "/cards/:n/assignees/:u", act((c, _b, m) => store.assign(c, m[1]!, true)));
on("DELETE", "/cards/:n/assignees/:u", act((c, _b, m) => store.assign(c, m[1]!, false)));
on("PUT", "/cards/:n/watch", ([n]) => (store.watch(store.card(num(n!)).id, store.me), NO_CONTENT));
on("DELETE", "/cards/:n/watch", ([n]) => (store.watches.delete(`${store.card(num(n!)).id}:${store.me}`), NO_CONTENT));
on("PUT", "/cards/:n/pin", ([n]) => {
  const c = store.card(num(n!));
  if (!store.pins.some((p) => p.user_id === store.me && p.card_id === c.id)) {
    const mine = store.pins.filter((p) => p.user_id === store.me);
    store.pins.push({ user_id: store.me, card_id: c.id, position: store.place(mine, null, (p) => p.card_id) });
  }
  return NO_CONTENT;
});
on("DELETE", "/cards/:n/pin", ([n]) => {
  const c = store.card(num(n!));
  store.pins = store.pins.filter((p) => !(p.user_id === store.me && p.card_id === c.id));
  return NO_CONTENT;
});
on("GET", "/pins", () =>
  store.pins
    .filter((p) => p.user_id === store.me)
    .sort((a, b) => (a.position < b.position ? -1 : 1))
    .map((p) => store.cards.find((c) => c.id === p.card_id))
    .filter((c): c is Card => !!c)
    .map((c) => store.tile(c)),
);

// Steps, comments, reactions, attachments -------------------------------------------------------
on("POST", "/cards/:n/steps", ([n], _q, b) => write(() => store.addStep(store.card(num(n!)), String(b.body ?? ""))));
const step = (id: string) => {
  const s = store.steps.find((x) => x.id === id);
  if (!s) throw new Problem(404, "Not found", "No such step");
  return { s, card: store.cards.find((c) => c.id === s.card_id)! };
};
on("PATCH", "/steps/:id", ([id], _q, b) =>
  write(() => {
    const { s, card } = step(id!);
    if (typeof b.body === "string" && b.body.trim()) s.body = b.body.trim();
    if (typeof b.completed === "boolean") store.completeStep(s, card, b.completed);
    store.bump(card.board_id);
    return s;
  }),
);
on("DELETE", "/steps/:id", ([id]) => {
  const { s, card } = step(id!);
  store.steps = store.steps.filter((x) => x !== s);
  store.bump(card.board_id);
  return NO_CONTENT;
});
on("POST", "/cards/:n/comments", ([n], _q, b) =>
  write(() => {
    const c = store.comment(store.card(num(n!)), b.body as RichText);
    return { ...c, reactions: [] };
  }),
);
const comment = (id: string) => {
  const c = store.comments.find((x) => x.id === id);
  if (!c) throw new Problem(404, "Not found", "No such comment");
  return c;
};
on("PATCH", "/comments/:id", ([id], _q, b) => {
  const c = comment(id!);
  if (c.author_id !== store.me) throw new Problem(403, "Not allowed", "Only the author can edit a comment");
  c.body = b.body as RichText;
  c.body_text = plainText(c.body);
  c.edited_at = store.now();
  return { ...c, reactions: [] };
});
on("DELETE", "/comments/:id", ([id]) => {
  const c = comment(id!);
  store.comments = store.comments.filter((x) => x !== c);
  return NO_CONTENT;
});
on("PUT", "/comments/:id/reactions/:emoji", ([id, e]) => write(() => (store.react(comment(id!).id, decodeURIComponent(e!), true), NO_CONTENT)));
on("DELETE", "/comments/:id/reactions/:emoji", ([id, e]) => write(() => (store.react(comment(id!).id, decodeURIComponent(e!), false), NO_CONTENT)));
on("POST", "/cards/:n/attachments", async ([n], _q, _b, req) => {
  const c = store.card(num(n!));
  const file = (await req.formData()).get("file") as File;
  const limit = 25 * 1024 * 1024;
  if (file.size > limit) throw new Problem(413, "Too large", "Attachments are limited to 25 MB");
  const a = {
    id: newId("att"),
    card_id: c.id,
    comment_id: null,
    filename: file.name,
    content_type: file.type || "application/octet-stream",
    bytes: file.size,
    uploaded_by: store.me,
    created_at: store.now(),
  };
  store.attachments.push(a);
  write(() => store.record("attached", c.board_id, c, { filename: file.name }));
  return a;
});
on("DELETE", "/attachments/:id", ([id]) => {
  const a = store.attachments.find((x) => x.id === id);
  if (a) {
    store.attachments = store.attachments.filter((x) => x !== a);
    store.bump(store.cards.find((c) => c.id === a.card_id)?.board_id ?? "");
  }
  return NO_CONTENT;
});

// Timeline, notifications, search ----------------------------------------------------------------
on("GET", "/events", (_m, q) => {
  const board = q.get("board");
  const visible = new Set(store.boards.filter((b) => store.canSee(b)).map((b) => b.id));
  const events = store.events
    .filter((e) => visible.has(e.board_id) && (!board || e.board_id === board))
    .reverse()
    .slice(0, Number(q.get("limit") ?? 50));
  return { events: events.map((e) => store.eventOut(e)), users: store.usersMap(), next_cursor: null };
});
on("GET", "/notifications", () => {
  const mine = store.notifications.filter((n) => n.user_id === store.me);
  const byCard = new Map<string, typeof mine>();
  for (const n of mine) byCard.set(n.card_id, [...(byCard.get(n.card_id) ?? []), n]);
  const seqOf = (eventId: string) => store.events.find((e) => e.id === eventId)?.seq ?? 0;
  const groups = [...byCard.entries()]
    .map(([cardId, list]) => {
      const latest = list.reduce((a, b) => (seqOf(a.event_id) > seqOf(b.event_id) ? a : b));
      const card = store.cards.find((c) => c.id === cardId)!;
      const board = store.boards.find((b) => b.id === card.board_id)!;
      const actors = [...list]
        .sort((a, b) => seqOf(b.event_id) - seqOf(a.event_id))
        .map((n) => store.events.find((e) => e.id === n.event_id)?.actor_id)
        .filter((x): x is string => !!x);
      return {
        seq: seqOf(latest.event_id),
        group: {
          card_id: card.id,
          card_number: card.number,
          card_title: card.title,
          board_id: board.id,
          board_name: board.name,
          unread: list.filter((n) => !n.read_at).length,
          total: list.length,
          latest: store.eventOut(store.events.find((e) => e.id === latest.event_id)!),
          actor_ids: [...new Set(actors)].slice(0, 5),
          reasons: [...new Set(list.map((n) => n.reason))].sort(),
        },
      };
    })
    .sort((a, b) => b.seq - a.seq);
  return { groups: groups.map((g) => g.group), users: store.usersMap(), next_cursor: null };
});
on("POST", "/notifications/read", (_m, _q, b) => {
  const ids = b.card_ids as string[] | null | undefined;
  for (const n of store.notifications)
    if (n.user_id === store.me && !n.read_at && (!ids || ids.includes(n.card_id))) n.read_at = store.now();
  return NO_CONTENT;
});
on("GET", "/search", (_m, q) => {
  const term = (q.get("q") ?? "").trim().toLowerCase();
  const snippet = (text: string) => {
    const i = text.toLowerCase().indexOf(term);
    if (i < 0) return null;
    const start = Math.max(0, i - 40);
    return `${start ? "…" : ""}${text.slice(start, i)}«${text.slice(i, i + term.length)}»${text.slice(i + term.length, i + term.length + 60)}…`;
  };
  const hits = store.cards
    .filter((c) => (c.status === "published" || c.created_by === store.me) && store.canSee(store.boards.find((b) => b.id === c.board_id)!))
    .map((c) => {
      const comments = store.comments.filter((m) => m.card_id === c.id).map((m) => m.body_text);
      const inTitle = c.title.toLowerCase().includes(term);
      const text = [c.description_text, ...comments].find((t) => t.toLowerCase().includes(term));
      return inTitle || text ? { c, rank: inTitle ? 2 : 1, snip: text ? snippet(text) : null } : null;
    })
    .filter((h): h is NonNullable<typeof h> => !!h)
    .sort((a, b) => b.rank - a.rank || b.c.number - a.c.number)
    .slice(0, 30);
  return {
    hits: hits.map((h) => ({ card: store.tile(h.c), board_name: store.boards.find((b) => b.id === h.c.board_id)!.name, snippet: h.snip })),
    users: store.usersMap(),
  };
});

// The fetch patch ------------------------------------------------------------------------------------
const realFetch = globalThis.fetch.bind(globalThis);

function respond(status: number, body?: unknown) {
  if (status === 204) return new Response(null, { status });
  const type = status >= 400 ? "application/problem+json" : "application/json";
  return new Response(JSON.stringify(body), { status, headers: { "content-type": type } });
}

globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const req = input instanceof Request ? input : new Request(input, init);
  const url = new URL(req.url, location.href);
  if (!url.pathname.startsWith("/api/")) return realFetch(input, init);
  await new Promise((r) => setTimeout(r, 60 + Math.random() * 60)); // feel like a network
  store.clock = () => Date.now();
  store.actor = store.me;
  for (const [method, re, handler] of routes) {
    const m = url.pathname.match(re);
    if (!m || method !== req.method) continue;
    try {
      const isJson = req.headers.get("content-type")?.includes("application/json");
      const body = isJson ? ((await req.clone().json().catch(() => ({}))) as Record<string, unknown>) : {};
      const result = await handler(m.slice(1), url.searchParams, body ?? {}, req);
      if (result === NO_CONTENT) return respond(204);
      return respond(200, result);
    } catch (err) {
      if (err instanceof Problem)
        return respond(err.status, { type: "about:blank", title: err.title, status: err.status, detail: err.message, ...err.extra });
      console.error(err);
      return respond(500, { type: "about:blank", title: "Preview error", status: 500, detail: String(err) });
    }
  }
  return respond(404, { type: "about:blank", title: "Not found", status: 404, detail: `${req.method} ${url.pathname} isn't in the preview` });
};
