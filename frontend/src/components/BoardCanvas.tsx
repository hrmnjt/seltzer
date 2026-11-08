/**
 * The board, Fizzy-style: lanes sit in a fixed row (Not Now, Maybe?, the columns, Done),
 * and only two are open at once — Maybe? plus the one you're focused on. Every other lane
 * folds into a narrow strip that still takes drops. Cards are never placed by hand: drop
 * one on any lane, open or folded, and it lands on top, because each lane lists golden
 * cards first and then the most recently active.
 */
import {
  DndContext,
  type DragEndEvent,
  type DragOverEvent,
  DragOverlay,
  type DragStartEvent,
  MouseSensor,
  pointerWithin,
  TouchSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { type BoardSnapshot, type CardTile, colorVar, type Schemas, type UsersMap } from "../api/client";
import { applyTile, cardApi, keys, refreshAfterCardWrite, usePile } from "../api/hooks";
import { DONE, type Filters, lanesOf, MAYBE, NOT_NOW } from "../lib/board";
import { CardTileView } from "./CardTile";
import { Composer } from "./Composer";
import { errorText, Icon, useToast } from "./ui";

type CardPage = Schemas["CardPage"];

type Lane = {
  id: string;
  title: string;
  color?: string; // a column colour name
  count: number;
  hint?: string;
};

const DESKTOP = "(min-width: 640px)";

function useIsDesktop() {
  const [desktop, setDesktop] = useState(() => window.matchMedia(DESKTOP).matches);
  useEffect(() => {
    const mq = window.matchMedia(DESKTOP);
    const onChange = () => setDesktop(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return desktop;
}

/** The lane you opened next to Maybe?, remembered per board in this browser. */
function useFocusedLane(boardId: string): [string | null, (lane: string | null) => void] {
  const key = `seltzer:open-lane:${boardId}`;
  const [lane, setLane] = useState<string | null>(() => {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  });
  const set = (next: string | null) => {
    setLane(next);
    try {
      if (next) localStorage.setItem(key, next);
      else localStorage.removeItem(key);
    } catch {
      /* storage can be unavailable; the board still works */
    }
  };
  return [lane, set];
}

type Props = {
  snap: BoardSnapshot;
  filters: Filters;
  onOpen: (number: number) => void;
  onAddColumn?: () => void;
};

export function BoardCanvas({ snap, filters, onOpen, onAddColumn }: Props) {
  const qc = useQueryClient();
  const toast = useToast();
  const desktop = useIsDesktop();
  const boardId = snap.board.id;
  const [focused, setFocused] = useFocusedLane(boardId);

  const lanes: Lane[] = useMemo(() => {
    const byLane = lanesOf(snap, filters);
    return [
      { id: NOT_NOW, title: "Not Now", color: "gray", count: snap.board.counts.not_now, hint: `Idle ${snap.board.effective_auto_postpone_days} days, or parked by hand` },
      { id: MAYBE, title: "Maybe?", count: byLane[MAYBE]?.length ?? 0, hint: "New cards land here" },
      ...snap.columns.map((c) => ({ id: c.id, title: c.name, color: c.color, count: byLane[c.id]?.length ?? 0 })),
      { id: DONE, title: "Done", color: "gray", count: snap.board.counts.done },
    ];
  }, [snap, filters]);

  // A remembered lane that no longer exists (a deleted column) is forgotten.
  const focus = focused && lanes.some((l) => l.id === focused) ? focused : null;
  const isOpen = (id: string) => (desktop ? id === MAYBE || id === focus : id === (focus ?? MAYBE));

  function toggle(id: string) {
    if (desktop) {
      if (id === MAYBE) return; // Maybe? always stays open on a wide screen
      setFocused(id === focus ? null : id);
    } else {
      setFocused(id === MAYBE ? null : id);
    }
  }

  // Open lanes on a phone scroll into view.
  const scroller = useRef<HTMLDivElement>(null);
  const openOnPhone = desktop ? null : (focus ?? MAYBE);
  useEffect(() => {
    if (!openOnPhone) return;
    scroller.current?.querySelector(`[data-lane="${CSS.escape(openOnPhone)}"]`)?.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
  }, [openOnPhone]);

  // Cards for open lanes: Maybe? and columns come with the board; Not Now and Done load on open.
  const byLane = useMemo(() => lanesOf(snap, filters), [snap, filters]);
  const notNow = usePile(boardId, "not_now", isOpen(NOT_NOW));
  const done = usePile(boardId, "done", isOpen(DONE));
  const tiles = useMemo(() => {
    const all = new Map<string, CardTile>();
    for (const c of snap.cards) all.set(c.id, c);
    for (const c of notNow.data?.cards ?? []) all.set(c.id, c);
    for (const c of done.data?.cards ?? []) all.set(c.id, c);
    return all;
  }, [snap.cards, notNow.data, done.data]);
  const users: UsersMap = { ...notNow.data?.users, ...done.data?.users, ...snap.users };

  const cardsIn = (lane: string): { ids: string[]; loading: boolean } => {
    if (lane === NOT_NOW) return { ids: notNow.data?.cards.map((c) => c.id) ?? [], loading: notNow.isLoading };
    if (lane === DONE) return { ids: done.data?.cards.map((c) => c.id) ?? [], loading: done.isLoading };
    return { ids: byLane[lane] ?? [], loading: false };
  };

  // Dragging --------------------------------------------------------------------------
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 220, tolerance: 8 } }),
  );
  const [drag, setDrag] = useState<{ tile: CardTile; from: string } | null>(null);
  const [over, setOver] = useState<string | null>(null);

  function onDragStart(e: DragStartEvent) {
    const data = e.active.data.current as { lane: string } | undefined;
    const tile = tiles.get(String(e.active.id));
    if (tile && data) setDrag({ tile, from: data.lane });
  }

  function onDragOver(e: DragOverEvent) {
    setOver(e.over ? String(e.over.id) : null);
  }

  async function onDragEnd(e: DragEndEvent) {
    const d = drag;
    setDrag(null);
    setOver(null);
    const to = e.over ? String(e.over.id) : null;
    if (!d || !to || to === d.from) return; // dropping back on its own lane changes nothing
    await move(qc, d.tile, d.from, to, toast);
  }

  const overLane = lanes.find((l) => l.id === over);

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={pointerWithin}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDragEnd={onDragEnd}
      onDragCancel={() => {
        setDrag(null);
        setOver(null);
      }}
    >
      <div ref={scroller} className="flex h-full min-h-0 gap-1.5 overflow-x-auto px-4 pb-4 sm:gap-2">
        {lanes.map((lane) =>
          isOpen(lane.id) ? (
            <OpenLane
              key={lane.id}
              lane={lane}
              boardId={boardId}
              collapsible={!(desktop && lane.id === MAYBE)}
              onCollapse={() => toggle(lane.id)}
              dragging={!!drag && drag.from !== lane.id}
            >
              <LaneCards lane={lane} {...cardsIn(lane.id)} tiles={tiles} users={users} onOpen={onOpen} />
            </OpenLane>
          ) : (
            <FoldedLane key={lane.id} lane={lane} onOpen={() => toggle(lane.id)} dragging={!!drag && drag.from !== lane.id} />
          ),
        )}
        {onAddColumn && (
          <button
            type="button"
            onClick={onAddColumn}
            className="flex w-9 shrink-0 flex-col items-center gap-2 rounded-xl border border-dashed border-line-strong pt-3 text-ink-3 hover:border-accent hover:text-accent"
            aria-label="Add a column"
            title="Add a column"
          >
            <Icon name="plus" size={16} />
          </button>
        )}
      </div>
      <DragOverlay dropAnimation={null}>
        {drag ? (
          <div className="w-72 max-w-[80vw]">
            <CardTileView tile={drag.tile} users={users} onOpen={() => {}} overlay accent={overLane?.color ?? laneColor(lanes, drag.from)} />
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}

function laneColor(lanes: Lane[], id: string) {
  return lanes.find((l) => l.id === id)?.color;
}

/** Move a card to another lane: update every cached view at once, then ask the server. */
async function move(qc: QueryClient, tile: CardTile, from: string, to: string, toast: (t: string) => void) {
  const boardId = tile.board_id;
  const now = new Date().toISOString();
  const state = to === NOT_NOW ? "not_now" : to === DONE ? "done" : "active";
  const column_id = to === MAYBE || to === NOT_NOW ? null : to === DONE ? tile.column_id : to;
  const moved: CardTile = { ...tile, state, column_id, last_active_at: now, golden: tile.golden };

  qc.setQueryData<BoardSnapshot>(keys.board(boardId), (s) => {
    if (!s) return s;
    const counts = { ...s.board.counts };
    if (from === NOT_NOW) counts.not_now -= 1;
    if (from === DONE) counts.done -= 1;
    if (to === NOT_NOW) counts.not_now += 1;
    if (to === DONE) counts.done += 1;
    const cards = s.cards.filter((c) => c.id !== tile.id);
    return { ...s, board: { ...s.board, counts }, cards: state === "active" ? [moved, ...cards] : cards };
  });
  for (const [pile, view] of [
    [NOT_NOW, "not_now"],
    [DONE, "done"],
  ] as const) {
    qc.setQueryData<CardPage>(keys.pile(boardId, view), (page) => {
      if (!page) return page;
      const rest = page.cards.filter((c) => c.id !== tile.id);
      return { ...page, cards: to === pile ? [moved, ...rest] : rest };
    });
  }

  try {
    const res =
      to === MAYBE
        ? await cardApi.untriage(tile.number)
        : to === NOT_NOW
          ? await cardApi.postpone(tile.number)
          : to === DONE
            ? await cardApi.close(tile.number)
            : await cardApi.triage(tile.number, to);
    applyTile(qc, res.card, res.users);
  } catch (err) {
    toast(errorText(err));
  }
  refreshAfterCardWrite(qc, boardId, tile.number);
}

function DraggableTile({ tile, lane, users, onOpen, accent }: { tile: CardTile; lane: string; users: UsersMap; onOpen: (n: number) => void; accent?: string }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: tile.id, data: { lane } });
  // The tile's own button is the keyboard stop; moving by keyboard is in the card's "Move to…" menu.
  const { role: _role, tabIndex: _tab, ...describe } = attributes;
  return (
    <li ref={setNodeRef} {...describe} {...listeners} className="touch-manipulation">
      <CardTileView tile={tile} users={users} onOpen={onOpen} dragging={isDragging} accent={accent} />
    </li>
  );
}

function LaneCards({
  lane,
  ids,
  loading,
  tiles,
  users,
  onOpen,
}: {
  lane: Lane;
  ids: string[];
  loading: boolean;
  tiles: Map<string, CardTile>;
  users: UsersMap;
  onOpen: (n: number) => void;
}) {
  if (loading) return <p className="px-1 py-2 text-[12.5px] text-ink-3">Loading…</p>;
  if (ids.length === 0) return <p className="rounded-lg border border-dashed border-line px-3 py-4 text-center text-[12.5px] text-ink-3">{EMPTY[lane.id] ?? "Drop cards here"}</p>;
  return (
    <ul className="flex flex-col gap-2">
      {ids.map((id) => {
        const tile = tiles.get(id);
        return tile ? <DraggableTile key={id} tile={tile} lane={lane.id} users={users} onOpen={onOpen} accent={lane.color !== "gray" ? lane.color : undefined} /> : null;
      })}
    </ul>
  );
}

const EMPTY: Record<string, string> = {
  [MAYBE]: "Nothing to triage. New cards land here.",
  [NOT_NOW]: "Nothing parked. Idle cards drift here on their own.",
  [DONE]: "Nothing closed yet.",
};

function OpenLane({
  lane,
  boardId,
  collapsible,
  onCollapse,
  dragging,
  children,
}: {
  lane: Lane;
  boardId: string;
  collapsible: boolean;
  onCollapse: () => void;
  dragging: boolean;
  children: ReactNode;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: lane.id });
  const ring = isOver && dragging;
  return (
    <section
      ref={setNodeRef}
      id={`lane-${lane.id}`}
      data-lane={lane.id}
      aria-label={lane.title}
      className={`flex w-[min(85vw,22rem)] shrink-0 flex-col rounded-xl border bg-surface-2/60 transition-colors sm:w-auto sm:max-w-[30rem] sm:min-w-[19rem] sm:flex-1 sm:basis-0 ${
        ring ? "border-accent bg-accent-soft/50" : "border-line"
      }`}
      style={lane.color && lane.color !== "gray" ? { borderTop: `3px solid ${colorVar(lane.color)}` } : undefined}
    >
      <header className="flex items-center gap-2 px-3 pt-2.5 pb-2">
        <button
          type="button"
          onClick={collapsible ? onCollapse : undefined}
          disabled={!collapsible}
          aria-expanded="true"
          aria-controls={`lane-${lane.id}`}
          className="flex min-w-0 items-center gap-2 rounded-md text-left enabled:hover:text-accent"
          title={collapsible ? `Fold ${lane.title}` : undefined}
        >
          <h2 className="truncate text-[13px] font-semibold text-ink">{lane.title}</h2>
          <span className="rounded-full bg-surface-3 px-1.5 text-[11px] font-medium text-ink-2 tabular-nums">{lane.count}</span>
        </button>
        {lane.hint && <span className="truncate text-[11px] text-ink-3">{lane.hint}</span>}
        <span className="flex-1" />
        {collapsible && (
          <button type="button" onClick={onCollapse} className="rounded p-0.5 text-ink-3 hover:bg-surface-3" aria-label={`Fold ${lane.title}`}>
            <Icon name="x" size={14} />
          </button>
        )}
      </header>
      {lane.id === MAYBE && (
        <div className="px-2 pb-2">
          <Composer boardId={boardId} />
        </div>
      )}
      <div className="min-h-16 flex-1 overflow-y-auto px-2 pb-2">{children}</div>
    </section>
  );
}

/** A folded lane: its name, how many cards it holds, and a drop target. */
function FoldedLane({ lane, onOpen, dragging }: { lane: Lane; onOpen: () => void; dragging: boolean }) {
  const { setNodeRef, isOver } = useDroppable({ id: lane.id });
  const hot = isOver && dragging;
  const color = colorVar(lane.color ?? "gray");
  return (
    <button
      ref={setNodeRef}
      type="button"
      data-lane={lane.id}
      onClick={onOpen}
      aria-expanded="false"
      aria-label={`${lane.title}, ${lane.count} ${lane.count === 1 ? "card" : "cards"}. Open lane`}
      title={`Open ${lane.title}`}
      className={`group flex w-9 shrink-0 flex-col items-center gap-2 rounded-xl border pt-2.5 pb-3 transition-all sm:w-10 ${
        hot ? "w-14 border-transparent text-white sm:w-16" : "border-line bg-surface hover:border-line-strong"
      }`}
      style={hot ? { background: color } : undefined}
    >
      <span className={`text-[12px] font-semibold tabular-nums ${hot ? "" : "text-ink"}`}>{lane.count > 99 ? "99+" : lane.count}</span>
      <span className="flex flex-col items-center gap-[3px]" aria-hidden="true">
        {Array.from({ length: Math.min(lane.count, 8) }, (_, i) => (
          <span key={i} className="h-[3px] w-4 rounded-full opacity-80" style={{ background: hot ? "currentColor" : color }} />
        ))}
      </span>
      <span className={`text-[12px] font-semibold [writing-mode:vertical-rl] ${hot ? "" : "text-ink-2 group-hover:text-ink"}`}>
        {lane.title}
      </span>
    </button>
  );
}
