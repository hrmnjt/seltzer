import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { applyTile, cardApi, refreshAfterCardWrite } from "../api/hooks";
import { errorText, Icon, useToast } from "./ui";

/** "New card" input at the top of Maybe?. Enter files it; the draft button keeps it private. */
export function Composer({ boardId }: { boardId: string }) {
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const toast = useToast();

  async function submit(draft: boolean) {
    const text = title.trim();
    if (!text || busy) return;
    setBusy(true);
    try {
      const res = await cardApi.create(boardId, text, draft);
      applyTile(qc, res.card, res.users);
      setTitle("");
      refreshAfterCardWrite(qc, boardId);
      if (draft) toast(`Saved #${res.card.number} as a draft. Only you can see it.`, "info");
    } catch (err) {
      toast(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void submit(false);
      }}
      className="flex items-center gap-1 rounded-lg border border-line bg-surface px-2 focus-within:border-accent"
    >
      <Icon name="plus" size={14} className="text-ink-3" />
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="File a card…"
        aria-label="New card title"
        className="min-w-0 flex-1 bg-transparent py-1.5 text-[13px] outline-none placeholder:text-ink-3"
        maxLength={300}
      />
      {title.trim() && (
        <button
          type="button"
          onClick={() => void submit(true)}
          className="rounded px-1.5 py-0.5 text-[11px] text-ink-3 hover:bg-surface-2 hover:text-ink"
          title="Save as a private draft"
        >
          Draft
        </button>
      )}
    </form>
  );
}
