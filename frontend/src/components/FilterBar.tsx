import type { BoardSnapshot, UserOut } from "../api/client";
import type { Filters } from "../lib/board";

type Props = {
  snap: BoardSnapshot;
  people: UserOut[];
  filters: Filters;
  onChange: (f: Filters) => void;
};

const VIEWS: { id: NonNullable<Filters["view"]>; label: string }[] = [
  { id: "open", label: "Everything open" },
  { id: "golden", label: "Golden" },
  { id: "closing_soon", label: "Closing soon" },
];

export function FilterBar({ snap, people, filters, onChange }: Props) {
  const view = filters.view ?? "open";
  const closingSoon = snap.cards.filter((c) => c.closing_soon).length;
  const golden = snap.cards.filter((c) => c.golden).length;
  const active = filters.tag || filters.assignee || view !== "open";
  return (
    <div className="flex flex-wrap items-center gap-2 px-4 pb-3" role="toolbar" aria-label="Filters">
      <div className="flex rounded-lg border border-line bg-surface p-0.5">
        {VIEWS.map((v) => (
          <button
            type="button"
            key={v.id}
            aria-pressed={view === v.id}
            onClick={() => onChange({ ...filters, view: v.id === "open" ? undefined : v.id })}
            className={`rounded-md px-2.5 py-1 text-[12.5px] font-medium ${
              view === v.id ? "bg-accent-soft text-ink" : "text-ink-2 hover:text-ink"
            }`}
          >
            {v.label}
            {v.id === "golden" && golden > 0 && <span className="ml-1 text-ink-3">{golden}</span>}
            {v.id === "closing_soon" && closingSoon > 0 && <span className="ml-1 text-ink-3">{closingSoon}</span>}
          </button>
        ))}
      </div>
      <select
        value={filters.tag ?? ""}
        onChange={(e) => onChange({ ...filters, tag: e.target.value || undefined })}
        aria-label="Filter by tag"
        className="rounded-lg border border-line bg-surface px-2 py-1 text-[12.5px] text-ink-2"
      >
        <option value="">Any tag</option>
        {snap.tags.map((t) => (
          <option key={t.id} value={t.id}>
            #{t.name}
          </option>
        ))}
      </select>
      <select
        value={filters.assignee ?? ""}
        onChange={(e) => onChange({ ...filters, assignee: e.target.value || undefined })}
        aria-label="Filter by assignee"
        className="rounded-lg border border-line bg-surface px-2 py-1 text-[12.5px] text-ink-2"
      >
        <option value="">Anyone</option>
        {people.map((u) => (
          <option key={u.id} value={u.id}>
            {u.display_name}
          </option>
        ))}
      </select>
      {active && (
        <button type="button" onClick={() => onChange({})} className="text-[12.5px] text-accent hover:underline">
          Clear filters
        </button>
      )}
      <span className="flex-1" />
      <span className="hidden text-[12px] text-ink-3 md:inline">
        {snap.board.counts.open} open · auto-postpone after {snap.board.effective_auto_postpone_days} days idle
      </span>
    </div>
  );
}
