import { useNavigate } from "@tanstack/react-router";
import { Popover } from "radix-ui";
import { useEffect, useRef, useState } from "react";
import { useSearch } from "../api/hooks";
import { Icon, Kbd } from "./ui";

/** Search across card titles, descriptions and comments. "/" focuses it. */
export function SearchBox() {
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const results = useSearch(q);

  useEffect(() => {
    const t = setTimeout(() => setQ(text.trim()), 200);
    return () => clearTimeout(t);
  }, [text]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (e.key === "/" && !target.closest("input, textarea, [contenteditable=true]")) {
        e.preventDefault();
        input.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const hits = results.data?.hits ?? [];

  return (
    <Popover.Root open={open && q.length > 0} onOpenChange={setOpen}>
      <Popover.Anchor asChild>
        <div className="flex w-72 items-center gap-1.5 rounded-lg border border-line bg-surface-2 px-2 focus-within:border-accent focus-within:bg-surface">
          <Icon name="search" size={14} className="text-ink-3" />
          <input
            ref={input}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setText("");
                input.current?.blur();
              }
            }}
            placeholder="Search cards and comments"
            aria-label="Search"
            className="min-w-0 flex-1 bg-transparent py-1.5 text-[13px] outline-none placeholder:text-ink-3"
          />
          <Kbd>/</Kbd>
        </div>
      </Popover.Anchor>
      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={6}
          onOpenAutoFocus={(e) => e.preventDefault()}
          className="z-50 max-h-[60vh] w-[440px] overflow-y-auto rounded-xl border border-line bg-surface p-1 shadow-lift"
        >
          {results.isFetching && hits.length === 0 && <p className="p-3 text-[13px] text-ink-3">Searching…</p>}
          {!results.isFetching && hits.length === 0 && <p className="p-3 text-[13px] text-ink-3">No cards match “{q}”.</p>}
          {hits.map((h) => (
            <button
              type="button"
              key={h.card.id}
              onClick={() => {
                setOpen(false);
                void navigate({ to: "/boards/$boardId", params: { boardId: h.card.board_id }, search: { card: h.card.number } });
              }}
              className="block w-full rounded-lg px-2.5 py-2 text-left hover:bg-surface-2"
            >
              <span className="block truncate text-[13px] font-medium">
                <span className="font-mono text-[11px] text-ink-3">#{h.card.number}</span> {h.card.title}
              </span>
              {h.snippet && <span className="mt-0.5 block truncate text-[12px] text-ink-2">{h.snippet}</span>}
              <span className="block text-[11px] text-ink-3">
                {h.board_name} · {h.card.state === "done" ? "Done" : h.card.state === "not_now" ? "Not Now" : "Open"}
              </span>
            </button>
          ))}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
