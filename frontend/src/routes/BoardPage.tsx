import { useNavigate } from "@tanstack/react-router";
import { lazy, Suspense, useState } from "react";
import { api, call } from "../api/client";
import { useBoard, useUsers } from "../api/hooks";
import { BoardCanvas } from "../components/BoardCanvas";
import { BoardSettings } from "../components/BoardSettings";
import { FilterBar } from "../components/FilterBar";
import { Button, errorText, Icon } from "../components/ui";
import type { Filters } from "../lib/board";

// The card sheet carries the rich-text editor, so it loads on first open.
const CardSheet = lazy(() => import("../components/CardSheet").then((m) => ({ default: m.CardSheet })));

export type BoardSearch = { card?: number; view?: Filters["view"]; tag?: string; assignee?: string };

export function BoardPage({ boardId, search }: { boardId: string; search: BoardSearch }) {
  const board = useBoard(boardId);
  const users = useUsers();
  const navigate = useNavigate();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const filters: Filters = { view: search.view, tag: search.tag, assignee: search.assignee };

  const setSearch = (next: BoardSearch) =>
    void navigate({ to: "/boards/$boardId", params: { boardId }, search: next, replace: true });

  if (board.isError) return <p className="p-6 text-ink-2">{errorText(board.error)}</p>;
  if (!board.data) return <p className="p-6 text-ink-3">Loading board…</p>;
  const snap = board.data;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-3 px-4 pt-4 pb-3">
        <h1 className="text-[18px] font-semibold">{snap.board.name}</h1>
        {!snap.board.all_access && <span className="rounded-full bg-surface-2 px-2 text-[11.5px] text-ink-3">restricted</span>}
        {snap.board.archived_at && <span className="rounded-full bg-danger-soft px-2 text-[11.5px] text-danger">archived</span>}
        <span className="flex-1" />
        {snap.drafts.length > 0 && (
          <span className="text-[12.5px] text-ink-3">
            Your drafts:{" "}
            {snap.drafts.map((d) => (
              <button type="button" key={d.id} onClick={() => setSearch({ ...search, card: d.number })} className="ml-1 text-accent hover:underline">
                #{d.number}
              </button>
            ))}
          </span>
        )}
        <Button
          variant="ghost"
          onClick={async () => {
            const path = { params: { path: { board_id: boardId } } };
            await call(snap.board.watching ? api.DELETE("/api/boards/{board_id}/watch", path) : api.PUT("/api/boards/{board_id}/watch", path));
            void board.refetch();
          }}
          aria-pressed={snap.board.watching}
        >
          <Icon name="eye" size={14} /> {snap.board.watching ? "Watching" : "Watch"}
        </Button>
        <Button variant="ghost" onClick={() => setSettingsOpen(true)}>
          <Icon name="gear" size={14} /> Settings
        </Button>
      </div>
      <FilterBar
        snap={snap}
        people={users.data ?? []}
        filters={filters}
        onChange={(f) => setSearch({ card: search.card, ...f })}
      />
      <div className="min-h-0 flex-1">
        <BoardCanvas snap={snap} filters={filters} onOpen={(n) => setSearch({ ...search, card: n })} />
      </div>
      {search.card != null && (
        <Suspense fallback={null}>
          <CardSheet number={search.card} columns={snap.columns} onClose={() => setSearch({ ...search, card: undefined })} />
        </Suspense>
      )}
      <BoardSettings snap={snap} open={settingsOpen} onOpenChange={setSettingsOpen} />
    </div>
  );
}
