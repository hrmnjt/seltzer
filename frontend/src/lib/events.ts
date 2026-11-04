import type { EventOut, UsersMap } from "../api/client";

/** One line describing an event, e.g. "Ada moved it to Review". */
export function describe(e: EventOut, users: UsersMap, opts: { withCard?: boolean } = {}): string {
  const who = e.actor_id ? (users[e.actor_id]?.display_name ?? "Someone") : "Seltzer";
  const d = e.details as Record<string, string | number | null | undefined>;
  const card = opts.withCard && e.card_number ? `#${e.card_number}` : "it";
  switch (e.action) {
    case "published":
      return `${who} filed ${card}`;
    case "triaged":
      return `${who} put ${card} in ${d.column ?? "a column"}`;
    case "moved":
      return `${who} moved ${card} from ${d.from_column ?? "a column"} to ${d.column ?? "a column"}`;
    case "sent_back_to_triage":
      return `${who} sent ${card} back to Maybe?`;
    case "postponed":
      return `${who} moved ${card} to Not Now`;
    case "auto_postponed":
      return `Seltzer moved ${card} to Not Now after it sat idle`;
    case "resumed":
      return `${who} brought ${card} back from Not Now`;
    case "closed":
      return `${who} closed ${card}`;
    case "reopened":
      return `${who} reopened ${card}`;
    case "gilded":
      return `${who} gave ${card} a golden ticket`;
    case "ungilded":
      return `${who} took the golden ticket from ${card}`;
    case "assigned":
      return `${who} assigned ${d.name ?? "someone"} to ${card}`;
    case "unassigned":
      return `${who} unassigned ${d.name ?? "someone"} from ${card}`;
    case "tagged":
      return `${who} tagged ${card} #${d.tag ?? ""}`;
    case "untagged":
      return `${who} removed #${d.tag ?? ""} from ${card}`;
    case "title_changed":
      return `${who} renamed ${card} to “${d.to ?? ""}”`;
    case "description_changed":
      return `${who} edited the description of ${card}`;
    case "board_changed":
      return `${who} moved ${card} here from ${d.from_board ?? "another board"}`;
    case "commented":
      return `${who} commented on ${card}`;
    case "step_added":
      return `${who} added a step to ${card}`;
    case "step_completed":
      return `${who} checked off “${d.step ?? ""}”`;
    case "step_uncompleted":
      return `${who} unchecked “${d.step ?? ""}”`;
    case "attached":
      return `${who} attached ${d.filename ?? "a file"}`;
    case "deleted":
      return `${who} deleted #${d.number ?? "?"} “${d.title ?? ""}”`;
    default:
      return `${who} updated ${card}`;
  }
}
