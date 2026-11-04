import {
  closestCorners,
  DndContext,
  type DragEndEvent,
  type DragOverEvent,
  DragOverlay,
  type DragStartEvent,
  KeyboardSensor,
  PointerSensor,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { arrayMove, SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { type BoardSnapshot, type CardTile, colorVar, type UsersMap } from "../api/client";
import { cardApi, keys, refreshAfterCardWrite, applyTile, usePile } from "../api/hooks";
import { DONE, type Filters, lanesOf, MAYBE, NOT_NOW } from "../lib/board";
import { keyBetween } from "../lib/ordering";
import { CardTileView, SortableTile } from "./CardTile";
import { Composer } from "./Composer";
import { errorText, Icon, useToast } from "./ui";

type Props = {
  snap: BoardSnapshot;
  filters: Filters;
  onOpen: (number: number) => void;
};

export function BoardCanvas({ snap, filters, onOpen }: Props) {
  const qc = useQueryClient();
  const toast = useToast();
  const cards = useMemo(() => new Map(snap.cards.map((c) => [c.id, c])), [snap.cards]);
  const serverLanes = useMemo(() => lanesOf(snap, filters), [snap, filters]);
  const [lanes, setLanes] = useState(serverLanes);
  const [active, setActive] = useState<{ id: string; from: string } | null>(null);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  // Follow the server unless a drag is in flight.
  useEffect(() => {
    if (!active) setLanes(serverLanes);
  }, [serverLanes, active]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const laneOf = (id: string): string | undefined => {
    if (id in lanes || id === NOT_NOW || id === DONE) return id;
    return Object.keys(lanes).find((lane) => lanes[lane]!.includes(id));
  };

  function onDragStart(e: DragStartEvent) {
    const id = String(e.active.id);
    setActive({ id, from: laneOf(id) ?? MAYBE });
  }

  function onDragOver(e: DragOverEvent) {
    if (!e.over) return;
    const id = String(e.active.id);
    const from = laneOf(id);
    const to = laneOf(String(e.over.id));
    if (!from || !to || from === to || to === NOT_NOW || to === DONE) return;
    setLanes((prev) => {
      const source = prev[from]!.filter((x) => x !== id);
      const target = [...prev[to]!];
      const overIndex = target.indexOf(String(e.over!.id));
      target.splice(overIndex >= 0 ? overIndex : target.length, 0, id);
      return { ...prev, [from]: source, [to]: target };
    });
  }

  async function onDragEnd(e: DragEndEvent) {
    const drag = active;
    setActive(null);
    if (!drag || !e.over) {
      setLanes(serverLanes);
      return;
    }
    const id = drag.id;
    const card = cards.get(id);
    if (!card) return;
    const to = laneOf(String(e.over.id));
    if (!to) return;

    if (to === NOT_NOW || to === DONE) {
      setLanes(serverLanes);
      const optimistic = { ...card, state: to === DONE ? "done" : "not_now" } as CardTile;
      patchSnapshot(optimistic);
      try {
        const res = to === DONE ? await cardApi.close(card.number) : await cardApi.postpone(card.number);
        applyTile(qc, res.card, res.users);
      } catch (err) {
        toast(errorText(err));
      }
      refreshAfterCardWrite(qc, snap.board.id, card.number);
      return;
    }

    let list = lanes[to]!;
    const overId = String(e.over.id);
    if (drag.from === to && overId !== to) {
      const oldIndex = list.indexOf(id);
      const newIndex = list.indexOf(overId);
      if (oldIndex !== newIndex) list = arrayMove(list, oldIndex, newIndex);
      else if (drag.from === to) {
        setLanes(serverLanes);
        return; // dropped where it was
      }
    }
    setLanes((prev) => ({ ...prev, [to]: list }));
    const index = list.indexOf(id);
    const above = index > 0 ? list[index - 1]! : null;
    const below = index < list.length - 1 ? list[index + 1]! : null;
    const position = keyBetween(above ? cards.get(above)?.position : null, below ? cards.get(below)?.position : null);
    patchSnapshot({ ...card, column_id: to === MAYBE ? null : to, position });

    try {
      const res =
        to === MAYBE
          ? drag.from === MAYBE
            ? await cardApi.reorder(card.number, above, below)
            : await cardApi.untriage(card.number, above, below)
          : await cardApi.triage(card.number, to, above, below);
      applyTile(qc, res.card, res.users);
    } catch (err) {
      toast(errorText(err));
    }
    refreshAfterCardWrite(qc, snap.board.id, card.number);
  }

  function patchSnapshot(tile: CardTile) {
    qc.setQueryData<BoardSnapshot>(keys.board(snap.board.id), (s) =>
      s ? { ...s, cards: s.cards.filter((c) => c.id !== tile.id).concat(tile.state === "active" ? [tile] : []) } : s,
    );
  }

  const activeTile = active ? cards.get(active.id) : undefined;
  const columnColor = (laneId: string) => snap.columns.find((c) => c.id === laneId)?.color;

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDragEnd={onDragEnd}
      onDragCancel={() => {
        setActive(null);
        setLanes(serverLanes);
      }}
    >
      <div className="flex h-full min-h-0 gap-3 overflow-x-auto px-4 pb-4">
        <Lane
          id={MAYBE}
          title="Maybe?"
          subtitle="New cards land here"
          wide
          count={lanes[MAYBE]!.length}
          header={<Composer boardId={snap.board.id} />}
        >
          <LaneCards ids={lanes[MAYBE]!} lane={MAYBE} cards={cards} users={snap.users} onOpen={onOpen} />
        </Lane>
        {snap.columns.map((col) => {
          const isCollapsed = collapsed[col.id] ?? false;
          return (
            <Lane
              key={col.id}
              id={col.id}
              title={col.name}
              color={col.color}
              count={lanes[col.id]?.length ?? 0}
              collapsed={isCollapsed}
              onToggle={() => setCollapsed((c) => ({ ...c, [col.id]: !isCollapsed }))}
            >
              <LaneCards
                ids={lanes[col.id] ?? []}
                lane={col.id}
                cards={cards}
                users={snap.users}
                onOpen={onOpen}
                accent={col.color}
              />
            </Lane>
          );
        })}
        {snap.columns.length === 0 && (
          <div className="flex w-60 shrink-0 flex-col justify-center rounded-xl border border-dashed border-line-strong p-4 text-[13px] text-ink-2">
            <p className="font-medium text-ink">No columns yet</p>
            <p className="mt-1">Add workflow stages such as “Doing” and “Review” in board settings, then drag cards out of Maybe?.</p>
          </div>
        )}
        <div className="flex w-56 shrink-0 flex-col gap-3">
          <Pile boardId={snap.board.id} id={NOT_NOW} title="Not Now" count={snap.board.counts.not_now} onOpen={onOpen} icon="clock" />
          <Pile boardId={snap.board.id} id={DONE} title="Done" count={snap.board.counts.done} onOpen={onOpen} icon="check" />
        </div>
      </div>
      <DragOverlay dropAnimation={null}>
        {activeTile ? (
          <div className="w-72">
            <CardTileView tile={activeTile} users={snap.users} onOpen={() => {}} overlay accent={columnColor(laneOf(activeTile.id) ?? "")} />
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}

function LaneCards({
  ids,
  lane,
  cards,
  users,
  onOpen,
  accent,
}: {
  ids: string[];
  lane: string;
  cards: Map<string, CardTile>;
  users: UsersMap;
  onOpen: (n: number) => void;
  accent?: string;
}) {
  return (
    <SortableContext items={ids} strategy={verticalListSortingStrategy}>
      <div className="flex flex-col gap-2">
        {ids.map((id) => {
          const tile = cards.get(id);
          return tile ? <SortableTile key={id} tile={tile} lane={lane} users={users} onOpen={onOpen} accent={accent} /> : null;
        })}
      </div>
    </SortableContext>
  );
}

function Lane({
  id,
  title,
  subtitle,
  color,
  count,
  wide,
  collapsed,
  onToggle,
  header,
  children,
}: {
  id: string;
  title: string;
  subtitle?: string;
  color?: string;
  count: number;
  wide?: boolean;
  collapsed?: boolean;
  onToggle?: () => void;
  header?: ReactNode;
  children: ReactNode;
}) {
  const { setNodeRef, isOver } = useDroppable({ id });
  if (collapsed) {
    return (
      <button
        ref={setNodeRef}
        type="button"
        onClick={onToggle}
        className={`flex w-10 shrink-0 flex-col items-center gap-2 rounded-xl border border-line bg-surface-2 py-3 ${isOver ? "ring-2 ring-accent" : ""}`}
        title={`Expand ${title}`}
      >
        <span className="size-2.5 rounded-full" style={{ background: colorVar(color ?? "gray") }} />
        <span className="text-[12px] font-semibold text-ink-2 [writing-mode:vertical-rl]">{title}</span>
        <span className="text-[11px] text-ink-3">{count}</span>
      </button>
    );
  }
  return (
    <section
      ref={setNodeRef}
      aria-label={title}
      className={`flex shrink-0 flex-col rounded-xl border bg-surface-2/60 ${wide ? "w-72" : "w-64"} ${
        isOver ? "border-accent" : "border-line"
      }`}
      style={color ? { borderTop: `3px solid ${colorVar(color)}` } : undefined}
    >
      <header className="flex items-center gap-2 px-3 pt-2.5 pb-2">
        <h2 className="text-[13px] font-semibold text-ink">{title}</h2>
        <span className="rounded-full bg-surface-3 px-1.5 text-[11px] font-medium text-ink-2">{count}</span>
        {subtitle && <span className="truncate text-[11px] text-ink-3">{subtitle}</span>}
        <span className="flex-1" />
        {onToggle && (
          <button type="button" onClick={onToggle} className="rounded p-0.5 text-ink-3 hover:bg-surface-3" title={`Collapse ${title}`}>
            <Icon name="chevron-right" size={14} />
          </button>
        )}
      </header>
      {header && <div className="px-2 pb-2">{header}</div>}
      <div className="min-h-16 flex-1 overflow-y-auto px-2 pb-2">{children}</div>
    </section>
  );
}

function Pile({
  boardId,
  id,
  title,
  count,
  onOpen,
  icon,
}: {
  boardId: string;
  id: typeof NOT_NOW | typeof DONE;
  title: string;
  count: number;
  onOpen: (n: number) => void;
  icon: "clock" | "check";
}) {
  const { setNodeRef, isOver } = useDroppable({ id });
  const [open, setOpen] = useState(false);
  const pile = usePile(boardId, id === DONE ? "done" : "not_now", open);
  const qc = useQueryClient();
  const toast = useToast();

  async function bringBack(tile: CardTile) {
    try {
      const res = id === DONE ? await cardApi.reopen(tile.number) : await cardApi.resume(tile.number);
      applyTile(qc, res.card, res.users);
    } catch (err) {
      toast(errorText(err));
    }
    refreshAfterCardWrite(qc, boardId, tile.number);
  }

  return (
    <section
      ref={setNodeRef}
      aria-label={title}
      className={`flex min-h-0 flex-col rounded-xl border border-dashed transition ${
        isOver ? "border-accent bg-accent-soft" : "border-line-strong bg-surface-2/40"
      } ${open ? "flex-1" : ""}`}
    >
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex items-center gap-2 px-3 py-2.5 text-left">
        <Icon name={icon} size={14} className="text-ink-3" />
        <span className="text-[13px] font-semibold text-ink">{title}</span>
        <span className="rounded-full bg-surface-3 px-1.5 text-[11px] font-medium text-ink-2">{count}</span>
        <span className="flex-1" />
        <Icon name={open ? "chevron-down" : "chevron-right"} size={14} className="text-ink-3" />
      </button>
      {!open && <p className="px-3 pb-3 text-[11px] text-ink-3">Drop a card here to {id === DONE ? "close it" : "park it"}.</p>}
      {open && (
        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
          {pile.isLoading && <p className="px-1 text-[12px] text-ink-3">Loading…</p>}
          {pile.data?.cards.length === 0 && <p className="px-1 text-[12px] text-ink-3">Nothing here.</p>}
          <ul className="flex flex-col gap-1">
            {pile.data?.cards.map((tile) => (
              <li key={tile.id} className="group flex items-center gap-1 rounded-md px-1.5 py-1 hover:bg-surface">
                <button type="button" className="min-w-0 flex-1 truncate text-left text-[12.5px]" onClick={() => onOpen(tile.number)}>
                  <span className="font-mono text-[11px] text-ink-3">#{tile.number}</span> {tile.title}
                  {tile.auto_postponed && <span className="ml-1 text-[11px] text-ink-3">(idle)</span>}
                </button>
                <button
                  type="button"
                  onClick={() => bringBack(tile)}
                  title={id === DONE ? "Reopen" : "Back to Maybe?"}
                  className="rounded p-0.5 text-ink-3 opacity-0 group-hover:opacity-100 hover:bg-surface-3 focus:opacity-100"
                >
                  <Icon name="undo" size={13} />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
