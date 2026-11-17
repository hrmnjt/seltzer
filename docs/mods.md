# Mods and hook points

**Status: draft for discussion (2026-11-17).** Nothing here is built yet. This page defines the
contract that mods will be written against, so it is the thing to argue about before any code.

A mod is a small package that changes how Seltzer behaves for a board: it can stop a move, react
to one, run on a schedule, add fields, add commands and add UI. Mods use the same hook points as
Seltzer's own defaults. Auto-postpone, the "closing soon" warning and the planned stalled-card
detector and webhooks are all written as mods, so if those cannot be built on these hooks, the
hooks are wrong.

Most mods will not be written by hand. The Seltzer agent ([docs/agent.md](agent.md)) uses these
hooks as its building blocks when it proposes a team's rules, fields and views, so the
data-only kinds (rules, fields, views) matter most.

## What mods can never change

These stay in the core, whatever is installed. They are what makes every Seltzer board readable
to everyone who opens it.

1. **The lifecycle.** A card is a draft, open (in Maybe? or a column), in Not Now, or Done. Mods
   cannot add states. They add columns, which are board configuration, or fields.
2. **Lane order.** Golden cards first, then the most recently active. A mod can offer a different
   view of a board, but the board's lanes always sort this way.
3. **One path for every change.** Every change goes through a domain function and is recorded by
   `activity.record()` in the same transaction. Mods never write core tables directly.
4. **Permissions.** Who can see and change a board is decided by the core. A mod acts either as
   the person who triggered it or as its own named identity, and only on boards where it is
   enabled.
5. **The event log is append-only.** Mods add their own event types, namespaced by mod, and can
   never edit or remove events.

This is the main difference from Jira. Jira lets admins redefine the lifecycle itself (statuses,
transitions, schemes per project), which is why big Jira setups need dedicated admins. Seltzer
keeps one lifecycle and lets mods work around it.

## The hook points

| Hook | When it runs | A mod receives | A mod can | Several mods | Jira's nearest equivalent |
| --- | --- | --- | --- | --- | --- |
| `before` | Inside the transaction, before a core change commits | The proposed change: action, card before and after, who, which board | Allow it, or deny it with a message the person sees | All run; any deny blocks; an error or a timeout (50 ms) counts as a deny | Workflow conditions and validators |
| `after` | After commit, in order per board, at least once | Each recorded event, core or mod | Call the mod API to make further changes | Each mod has its own cursor; one failing mod retries without holding up the others | Post functions, Automation rules, event triggers |
| `schedule` | Hourly, from the sweep job, for each board the mod is enabled on | The board and the time | Call the mod API | Each mod runs independently under the sweep's lock | Scheduled triggers and rules |
| `events` | Declared, read at startup | — | Register namespaced event types (`timetrack.logged`), a sentence for the timeline, and whether watchers are notified | Names cannot collide; the 24 core actions are reserved | Issue history entries |
| `fields` | Declared, read at startup | — | Add fields to cards (key, type, options), or a new field type with its own validation and display | Each field belongs to one mod; values outlive the mod | Custom fields and field types |
| `commands` | When a person or agent runs one | The card or board, the input, who ran it | Do work through the mod API | Each command belongs to one mod | Issue actions |
| `routes` | When an outside system calls `/api/mods/<mod>/…` | The request, verified as a signed webhook or a signed-in person | Do work through the mod API | Each mod owns its own path | Web triggers |
| `slots` | When the UI renders a named place | Typed props for that place (the card, the lane, the board) | Render React components from typed data, never HTML strings | All render, in order; one failing slot shows an error, not a blank board | Issue panels, glances, project pages, gadgets |

Commands also appear in the REST API, so whatever a mod adds is available to agents through the
same endpoints the UI uses.

### Places in the UI (`slots`)

| Slot | Where it renders | Example |
| --- | --- | --- |
| `card.badge` | On the card tile | "Moves to Not Now in 5d", an estimate, an SLA timer |
| `card.section` | In the card sheet | Time log, linked pull requests |
| `card.menu` | In the card's "Move to…" and actions menu | Commands from `commands` |
| `lane.header` | At the top of a lane | WIP count "3 / 4" |
| `board.toolbar` | Next to the filters | A filter on a mod's field |
| `board.view` | As an alternative view of the board | List, calendar, timeline |
| `board.settings` | In board settings | The mod's settings form (generated from its settings schema by default) |
| `home.panel` | On the home page | "My open cards across boards" |

## What a mod's code can call

Mods get a narrow context object (`ctx`), never a database session. Every call goes through the
same domain functions as the REST API, so permissions, events and notifications behave the same
whether a person, an agent or a mod made the change.

| Call | What it does |
| --- | --- |
| `ctx.cards.get / list / count / search` | Read cards on boards where the mod is enabled |
| `ctx.cards.create / move / postpone / close / reopen / tag / assign / comment / set_field` | Change cards. Recorded with the mod as the actor. **Does not float the card to the top of its lane** unless the mod passes `touch=True` |
| `ctx.events.record(action, card, details)` | Record one of the mod's own event types |
| `ctx.config` | This board's settings for the mod, validated against its schema |
| `ctx.state` | A small key/value store for the mod, per board |
| `ctx.http` | Outbound requests, only to hosts the mod declares |
| `ctx.log`, `ctx.now` | Logging and the current time |

Changes a mod makes inside an `after` handler carry a depth count. Anything past depth 3 is
dropped and logged, so two mods cannot trigger each other forever.

## What a mod looks like

A mod is one Python file, with an optional TypeScript file for UI. The core loads it, checks its
hook implementations against the hook definitions, and refuses to start a mod that implements a
hook that does not exist. Sketches only; the API names are not final.

A WIP limit, which needs only `before`:

```python
from pydantic import BaseModel
from seltzer.mods import Deny, Mod

mod = Mod(id="wip-limits", version="0.1.0", api="1")


@mod.settings
class Settings(BaseModel):
    limits: dict[str, int] = {}  # column name -> most open cards allowed


@mod.before("triaged", "moved")
async def enforce(change, ctx):
    column = change.to_column
    limit = ctx.config.limits.get(column.name)
    if limit and await ctx.cards.count(column=column) >= limit:
        return Deny(f"{column.name} already has {limit} cards. Finish one first.")
```

Auto-postpone, Seltzer's own default, rebuilt on `schedule`:

```python
from datetime import timedelta

from pydantic import BaseModel, Field
from seltzer.mods import Mod

mod = Mod(id="auto-postpone", version="1.0.0", api="1", on_by_default=True)


@mod.settings
class Settings(BaseModel):
    days: int = Field(30, ge=3, le=365)


@mod.schedule("hourly")
async def sweep(board, ctx):
    idle = timedelta(days=ctx.config.days)
    for card in await ctx.cards.list(board=board, state="open", idle_for=idle):
        await ctx.cards.postpone(card, auto=True)
```

Its "closing soon" badge, on the `card.badge` slot:

```tsx
export default defineSlot("card.badge", ({ card, config }) => {
  const left = daysLeft(card.last_active_at, config.days);
  return left <= config.days * 0.25 ? <Badge icon="clock">Moves to Not Now in {left}d</Badge> : null;
});
```

## Who can write which mods

The hook points are the same for everyone. What changes with trust is which hooks a mod can use
and where its code runs. A Seltzer mod acts on a shared board, so the trust model cannot be Pi's
"extensions run with your full permissions".

| Kind | Written as | Hooks it can use | Enabled by | Runs |
| --- | --- | --- | --- | --- |
| Rules | Data: trigger, condition (CEL), action, built in the UI or by an agent | `before`, `after`, `schedule`, `fields` | Board admins | In the core |
| Code mods | Python and TypeScript, reviewed and merged | All | Workspace owners, by deploying | In the app process |
| Sandboxed mods | Agent-written functions for what a rule can't express | `after`, `schedule`, `commands`; UI in an isolated iframe | Board admins, after reading what the mod will touch | In a sandbox with only `ctx` calls, after commit |
| Remote mods | Another app or job | `after` (as webhooks out), `routes` | Workspace owners | Outside the app, calling the REST API |

`before` is limited to rules and reviewed code, because it runs inside every move and must be fast
and correct.

## How this compares with Jira

None of these hook points is new. Jira has the same kinds through workflow conditions,
validators and post functions, custom fields, Automation, and Forge apps (event triggers, issue
panels, custom fields, workflow rules). Rovo can build Automation flows from a plain-language
description. Trello Power-Ups, Kanboard, Obsidian and Datasette have most of them too. What
Seltzer does differently is a set of choices, not inventions:

| | Jira | Seltzer with mods |
| --- | --- | --- |
| Size of the contract | A large platform: many schemes, Forge modules and REST APIs | One fixed lifecycle and a few hook points, small enough for an agent to hold whole and test against |
| The lifecycle | Yours to redefine per project | Fixed: Maybe?, columns, Not Now, Done |
| Seltzer's own defaults | Built into the product, not on Forge | Mods on the same hooks, which a board can switch off |
| Code extensions | Forge apps, built and deployed by developers | One-file mods in the repo, written with an agent against generated types and tests |

The mod system is not a reason for Seltzer to exist; Fizzy's way of working, running inside
Databricks, and owning the card history are. So build only the hooks the next features need,
starting with `after`, `schedule` and `fields`, and add the rest when a team asks.

## Proving the hooks

Build these first, as mods, before anyone else writes one:

1. **Auto-postpone and its "closing soon" badge**: moved out of the core (`schedule`, `fields`,
   `slots`).
2. **Stalled-card detection** (from the spec's Later list): `schedule` plus `card.badge`.
3. **Webhooks to Slack or Teams** (also Later): `after` plus a settings form.
4. **WIP limits**: `before` plus `lane.header`.

If any of these needs something the hooks don't offer, change the hooks before adding a fifth.

## Open decisions

1. **Keep the lifecycle closed?** Proposed: yes. Teams that want more stages add columns.
2. **Gates inside the transaction.** A slow `before` slows every move. Proposed: 50 ms budget,
   rules and reviewed code only.
3. **Mod changes don't float cards.** Proposed default: a mod editing a field does not reorder the
   board or reset the auto-postpone clock.
4. **Board mods first.** Personal mods (that change only what one person sees) can come later.
5. **Which kinds first.** Proposed: rules and code mods now; sandboxed mods once teams ask for
   something rules can't do.
