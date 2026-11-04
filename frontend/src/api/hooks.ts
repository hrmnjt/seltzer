import {
  type QueryClient,
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  ApiError,
  api,
  type BoardSnapshot,
  type CardTile,
  call,
  type RichText,
  type Schemas,
  type UsersMap,
} from "./client";

export const keys = {
  me: ["me"] as const,
  boards: ["boards"] as const,
  board: (id: string) => ["board", id] as const,
  card: (n: number) => ["card", n] as const,
  users: ["users"] as const,
  tags: ["tags"] as const,
  notifications: ["notifications"] as const,
  timeline: (board?: string) => ["timeline", board ?? "all"] as const,
  pile: (board: string, view: string) => ["pile", board, view] as const,
  search: (q: string) => ["search", q] as const,
  pins: ["pins"] as const,
  settings: ["settings"] as const,
};

export const POLL_MS = 10_000;

export function useMe() {
  return useQuery({
    queryKey: keys.me,
    queryFn: () => call(api.GET("/api/me")),
    refetchInterval: POLL_MS * 3,
  });
}

export function useBoards() {
  return useQuery({ queryKey: keys.boards, queryFn: () => call(api.GET("/api/boards")) });
}

/** The board snapshot. Polls with ?since=<version>; an unchanged board costs one 204. */
export function useBoard(boardId: string) {
  const qc = useQueryClient();
  return useQuery({
    queryKey: keys.board(boardId),
    queryFn: async () => {
      const previous = qc.getQueryData<BoardSnapshot>(keys.board(boardId));
      const { data, response, error } = await api.GET("/api/boards/{board_id}", {
        params: {
          path: { board_id: boardId },
          query: previous ? { since: previous.version } : {},
        },
      });
      if (response.status === 204 && previous) return previous;
      if (!response.ok || !data) {
        throw new ApiError(response.status, (error ?? {}) as Record<string, unknown>);
      }
      return data as BoardSnapshot;
    },
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
  });
}

export function useCard(number: number | null) {
  return useQuery({
    queryKey: keys.card(number ?? 0),
    queryFn: () => call(api.GET("/api/cards/{number}", { params: { path: { number: number! } } })),
    enabled: number != null,
    refetchInterval: POLL_MS,
  });
}

export function usePile(boardId: string, view: "not_now" | "done", enabled: boolean) {
  return useQuery({
    queryKey: keys.pile(boardId, view),
    queryFn: () =>
      call(
        api.GET("/api/boards/{board_id}/cards", {
          params: { path: { board_id: boardId }, query: { view, limit: 100 } },
        }),
      ),
    enabled,
  });
}

export function useUsers() {
  return useQuery({
    queryKey: keys.users,
    queryFn: () => call(api.GET("/api/users")),
    staleTime: 60_000,
  });
}

export function useTags() {
  return useQuery({ queryKey: keys.tags, queryFn: () => call(api.GET("/api/tags")) });
}

export function useNotifications(enabled = true) {
  return useQuery({
    queryKey: keys.notifications,
    queryFn: () => call(api.GET("/api/notifications")),
    enabled,
  });
}

export function useTimeline(boardId?: string) {
  return useQuery({
    queryKey: keys.timeline(boardId),
    queryFn: () =>
      call(api.GET("/api/events", { params: { query: { board: boardId, limit: 60 } } })),
    refetchInterval: POLL_MS * 3,
  });
}

export function useSearch(q: string) {
  return useQuery({
    queryKey: keys.search(q),
    queryFn: () => call(api.GET("/api/search", { params: { query: { q } } })),
    enabled: q.trim().length > 0,
    placeholderData: keepPreviousData,
  });
}

export function usePins() {
  return useQuery({ queryKey: keys.pins, queryFn: () => call(api.GET("/api/pins")) });
}

/** Put a card tile returned by a write into every cached view that shows it. */
export function applyTile(qc: QueryClient, tile: CardTile, users: UsersMap) {
  qc.setQueryData<BoardSnapshot>(keys.board(tile.board_id), (snap) => {
    if (!snap) return snap;
    const others = snap.cards.filter((c) => c.id !== tile.id);
    const drafts = snap.drafts.filter((c) => c.id !== tile.id);
    const isOpen = tile.status === "published" && tile.state === "active";
    return {
      ...snap,
      cards: isOpen ? [...others, tile] : others,
      drafts: tile.status === "draft" ? [tile, ...drafts] : drafts,
      users: { ...snap.users, ...users },
    };
  });
}

/** Invalidate everything a card write can change. */
export function refreshAfterCardWrite(qc: QueryClient, boardId: string, number?: number) {
  void qc.invalidateQueries({ queryKey: keys.board(boardId) });
  void qc.invalidateQueries({ queryKey: ["pile", boardId] });
  void qc.invalidateQueries({ queryKey: keys.boards });
  void qc.invalidateQueries({ queryKey: ["timeline"] });
  if (number != null) void qc.invalidateQueries({ queryKey: keys.card(number) });
}

type CardResponse = Schemas["CardResponse"];

/** A mutation that returns a card tile; applies it to caches, then refetches. */
export function useCardWrite<V>(fn: (vars: V) => Promise<CardResponse>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (res) => {
      applyTile(qc, res.card, res.users);
      refreshAfterCardWrite(qc, res.card.board_id, res.card.number);
    },
  });
}

export const cardApi = {
  create: (boardId: string, title: string, draft = false, description?: RichText | null) =>
    call(
      api.POST("/api/boards/{board_id}/cards", {
        params: { path: { board_id: boardId } },
        body: { title, draft, description: description ?? null },
      }),
    ),
  edit: (number: number, body: Schemas["CardPatch"]) =>
    call(api.PATCH("/api/cards/{number}", { params: { path: { number } }, body })),
  triage: (number: number, column_id: string, above?: string | null, below?: string | null) =>
    call(
      api.POST("/api/cards/{number}/triage", {
        params: { path: { number } },
        body: { column_id, above: above ?? null, below: below ?? null },
      }),
    ),
  untriage: (number: number, above?: string | null, below?: string | null) =>
    call(
      api.POST("/api/cards/{number}/untriage", {
        params: { path: { number } },
        body: { above: above ?? null, below: below ?? null },
      }),
    ),
  reorder: (number: number, above?: string | null, below?: string | null) =>
    call(
      api.POST("/api/cards/{number}/reorder", {
        params: { path: { number } },
        body: { above: above ?? null, below: below ?? null },
      }),
    ),
  publish: (number: number) =>
    call(api.POST("/api/cards/{number}/publish", { params: { path: { number } } })),
  postpone: (number: number) =>
    call(api.POST("/api/cards/{number}/postpone", { params: { path: { number } } })),
  resume: (number: number) =>
    call(api.POST("/api/cards/{number}/resume", { params: { path: { number } } })),
  close: (number: number) =>
    call(api.POST("/api/cards/{number}/close", { params: { path: { number } } })),
  reopen: (number: number) =>
    call(api.POST("/api/cards/{number}/reopen", { params: { path: { number } } })),
  gild: (number: number, on: boolean) =>
    on
      ? call(api.PUT("/api/cards/{number}/golden", { params: { path: { number } } }))
      : call(api.DELETE("/api/cards/{number}/golden", { params: { path: { number } } })),
  tag: (number: number, tagId: string, on: boolean) =>
    on
      ? call(api.PUT("/api/cards/{number}/tags/{tag_id}", { params: { path: { number, tag_id: tagId } } }))
      : call(
          api.DELETE("/api/cards/{number}/tags/{tag_id}", { params: { path: { number, tag_id: tagId } } }),
        ),
  assign: (number: number, userId: string, on: boolean) =>
    on
      ? call(
          api.PUT("/api/cards/{number}/assignees/{user_id}", {
            params: { path: { number, user_id: userId } },
          }),
        )
      : call(
          api.DELETE("/api/cards/{number}/assignees/{user_id}", {
            params: { path: { number, user_id: userId } },
          }),
        ),
};
