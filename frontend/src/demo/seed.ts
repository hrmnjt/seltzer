/**
 * Sample workspace for the design preview. Every change is replayed through the Store
 * at a back-dated time, so stamps, the timeline, notifications and "closing soon"
 * come out exactly as the real app would produce them. All people are fictional.
 */
import type { RichText } from "../api/client";
import type { Store, User } from "./store";

const DAY = 86_400_000;

const doc = (...parts: (string | { mention: User })[]): RichText => ({
  type: "doc",
  content: [
    {
      type: "paragraph",
      content: parts.map((p) =>
        typeof p === "string"
          ? { type: "text", text: p }
          : { type: "mention", attrs: { id: p.mention.id, label: p.mention.display_name } },
      ),
    },
  ],
});

export function seed(s: Store) {
  const now = Date.now();
  const person = (id: string, display_name: string, role: User["role"], seenDaysAgo: number): User => ({
    id,
    display_name,
    email: `${display_name.toLowerCase().replace(/[^a-z]+/g, ".")}@example.com`,
    role,
    active: true,
    last_seen_at: new Date(now - seenDaysAgo * DAY).toISOString(),
  });
  const ada = person("u-ada", "Ada Moreno", "owner", 0);
  const grace = person("u-grace", "Grace Kim", "admin", 0.1);
  const linus = person("u-linus", "Linus Berg", "member", 0.2);
  const kat = person("u-kat", "Katherine Obi", "member", 1);
  const tomas = person("u-tomas", "Tomás Reyes", "member", 0.6);
  s.users = [ada, grace, linus, kat, tomas];
  s.me = ada.id;

  const at = (daysAgo: number, who: User | null) => {
    s.clock = () => now - daysAgo * DAY;
    s.actor = who?.id ?? "";
  };
  const tag = (name: string, color: string) => {
    const t = { id: `tag-${name}`, name, color };
    s.tags.push(t);
    return t.id;
  };
  const bug = tag("bug", "red");
  const customer = tag("customer", "green");
  const infra = tag("infra", "indigo");
  const ux = tag("ux", "pink");
  const docs = tag("docs", "amber");

  at(100, grace);
  const ideas = s.createBoard("Ideas", true, 90, [{ name: "Exploring", color: "teal" }]);
  at(70, grace);
  s.createCard(ideas, "Import boards from Trello", {
    description: doc("Teams keep asking how to bring their old boards over. Columns map cleanly; labels become tags."),
  });

  at(60, ada);
  const platform = s.createBoard("Platform", true, null, [
    { name: "Investigating", color: "amber" },
    { name: "Building", color: "blue" },
    { name: "Review", color: "violet" },
  ]);
  const [investigating, building, review] = s.columns.filter((c) => c.board_id === platform.id).map((c) => c.id);

  at(45, linus);
  const rateLimit = s.createCard(platform, "Rate-limit the search endpoint");
  s.tag(rateLimit, infra, true);

  at(40, kat);
  const requests = s.createBoard("Customer requests", true, null, [
    { name: "Talking to them", color: "orange" },
    { name: "Scheduled", color: "green" },
  ]);

  at(24, grace);
  const contrast = s.createCard(platform, "Dark mode contrast on card tiles is too low", {
    description: doc("Secondary text on tiles falls below 4.5:1 in dark mode. Stamps are the worst offenders."),
  });
  s.tag(contrast, ux, true);

  at(14, null);
  s.sweep(); // the hourly job parks the idle rate-limit card

  at(12, linus);
  const driver = s.createCard(platform, "Upgrade the Postgres driver");
  s.tag(driver, infra, true);
  s.triage(driver, building!);
  at(10, ada);
  const tokenDocs = s.createCard(platform, "Document the Lakebase token rotation");
  s.tag(tokenDocs, docs, true);
  s.triage(tokenDocs, review!);
  at(8, grace);
  const rust = s.createCard(platform, "Rewrite the importer in Rust");
  at(7, kat);
  const csv = s.createCard(platform, "Export a board as CSV for the quarterly review", {
    description: doc("Finance wants open, done and auto-postponed counts per column, one row per card."),
  });
  s.tag(csv, customer, true);
  at(6.5, ada);
  s.triage(csv, investigating!);
  s.assign(csv, kat.id, true);
  at(6, grace);
  s.postpone(rust);
  at(6, kat);
  const sso = s.createCard(requests, "Acme wants SSO group sync");
  s.triage(sso, s.columns.find((c) => c.board_id === requests.id && c.name === "Talking to them")!.id);
  const bulk = s.createCard(requests, "Bulk-move cards between boards");
  s.triage(bulk, s.columns.find((c) => c.board_id === requests.id && c.name === "Scheduled")!.id);

  at(5, grace);
  const loop = s.createCard(platform, "Login loop when the SSO session expires", {
    description: doc(
      "After the workspace session expires, people bounce between the identity provider and Seltzer until they clear cookies. Seen on Safari and Chrome.",
    ),
  });
  s.tag(loop, bug, true);
  at(4.9, ada);
  s.triage(loop, investigating!);
  s.assign(loop, linus.id, true);
  s.gild(loop, true);
  at(4, linus);
  const sweep = s.createCard(platform, "Move the sweep job to serverless", {
    description: doc("Hourly, as the app's service principal, so it shares the app's Postgres role."),
  });
  s.tag(sweep, infra, true);
  s.triage(sweep, building!);
  s.assign(sweep, linus.id, true);
  at(3.9, linus);
  s.triage(loop, building!);
  for (const step of ["Reproduce on staging", "Refresh the token before the redirect", "Add a regression test"]) s.addStep(loop, step);
  at(3.8, linus);
  s.comment(loop, doc("Reproduced: the refresh token is dropped on the second redirect."));
  at(3.5, ada);
  const analytics = s.createCard(platform, "Board analytics dashboard over card events");
  at(3.4, grace);
  s.triage(analytics, investigating!);
  s.assign(analytics, ada.id, true);
  s.assign(analytics, kat.id, true);
  at(3.2, linus);
  s.close(driver);
  at(3, tomas);
  const uploads = s.createCard(platform, "Attachment uploads time out above 20 MB");
  s.tag(uploads, bug, true);
  at(2.9, grace);
  s.triage(uploads, building!);
  s.assign(uploads, tomas.id, true);
  at(2.8, tomas);
  s.addStep(uploads, "Reproduce with a 25 MB PDF", true);
  s.addStep(uploads, "Stream to the volume in chunks");
  at(2.5, ada);
  const keys = s.createCard(platform, "Keyboard shortcuts for moving cards between columns");
  s.tag(keys, ux, true);
  at(2.4, grace);
  const keysComment = s.comment(keys, doc("J and K to move between cards, and number keys for columns, would be lovely."));
  at(2.3, ada);
  s.react(keysComment.id, "👍", true);
  at(2.1, linus);
  s.completeStep(s.steps.find((x) => x.body === "Reproduce on staging")!, loop, true);
  at(2, grace);
  s.close(tokenDocs);
  const collapse = s.createCard(platform, "Remember collapsed columns per person");
  s.tag(collapse, ux, true);
  s.triage(collapse, review!);
  at(1.5, linus);
  s.triage(sweep, review!);
  at(1.4, tomas);
  s.comment(sweep, doc("Job identity is the open question. Running it as the app's service principal keeps one Postgres role."));
  at(1.2, grace);
  s.comment(loop, doc("", { mention: ada }, " can we ship this before Friday's rollout?"));
  at(1, kat);
  s.createCard(platform, "Slack digest of what moved this week");
  at(0.6, tomas);
  s.createCard(ideas, "Weekly email of cards closing soon");
  at(0.5, ada);
  s.createCard(platform, "Quarterly roadmap review notes", { draft: true });
  at(0.3, grace);
  const react = s.createCard(ideas, "Let people react to cards, not just comments");
  s.triage(react, s.columns.find((c) => c.board_id === ideas.id)!.id);
  at(0.2, linus);
  s.comment(analytics, doc("I can pull time-in-column straight from the events table."));

  // Ada has read everything older than a day; pins two cards.
  for (const n of s.notifications) {
    const ev = s.events.find((e) => e.id === n.event_id)!;
    if (n.user_id === ada.id && Date.parse(ev.created_at) < now - DAY) n.read_at = ev.created_at;
  }
  s.pins.push({ user_id: ada.id, card_id: loop.id, position: "V" }, { user_id: ada.id, card_id: analytics.id, position: "k" });

  s.clock = () => Date.now();
  s.actor = ada.id;
}
