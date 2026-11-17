# The Seltzer agent

**Status: draft for discussion (2026-11-17).** Nothing here is built yet.

Decided so far:

- Context comes from **Outlook email and Teams** first.
- Until decided otherwise, the agent only **drafts and proposes** when acting on email or Teams
  content. A person confirms every change to a board.

Seltzer gets one assistant that anyone on a team can talk to: in Seltzer, in Teams, or by email. It
plans with you: it turns what arrives in your inbox and chats into draft cards, triages Maybe?,
answers "what's going on?", and warns about stalled work. It also shapes each team's board. It
proposes columns, fields, rules and views that fit how that team works, and the team accepts or
rejects them. It works with Seltzer's primitives (cards, lanes, events, people) and the hook points
in [docs/mods.md](mods.md), never around them.

## Principles

The first four follow Linear's [Agent Interaction Guidelines](https://linear.app/developers/aig).

1. **The agent is a visible member of the workspace.** It has its own identity and badge, says it
   is an agent, and uses the same actions people use. Every change it makes is recorded in the
   event log under its name and can be undone.
2. **Delegate, don't assign.** A card's assignee is always a person. The agent can be added as a
   delegate working on that person's behalf, because an agent cannot be held accountable.
3. **Every piece of work is a visible session.** When the agent takes something on, it shows a
   session with its state (waiting for you, working, done, failed) on the card or in the panel.
   Silence is never a state.
4. **Acknowledge at once.** A light "working on it" appears immediately, and longer work reports
   progress.
5. **It sees only what the asking person can see.** It works through each person's own access: their
   boards, their mailbox, their chats. It never uses the app's wider access to read anything.
6. **Outside content is data, never instructions.** An email can contain text aimed at the agent.
   Anything that arrives from email or Teams can only produce drafts and proposals.

## How it fits together

```mermaid
flowchart LR
    outlook["Outlook mail"] -- Graph, as each person --> ingest
    teams["Teams chats and channels"] -- Graph, as each person --> ingest
    ingest["Ingest job: polls delta links every few minutes"] --> signals[("Signals: source, link, excerpt, owner")]
    person["A person, in Seltzer, Teams or email"] --> agent
    signals --> agent["Agent loop, in the Seltzer app"]
    agent -- "tools = Seltzer domain functions" --> core["Seltzer core: cards, lanes, events, permissions"]
    agent -- "Messages API" --> claude["Claude on Databricks model serving"]
    core --> board["Boards, drafts, proposals"]
```

Everything runs inside the Databricks workspace, as the spec requires. The agent loop lives in the
Seltzer app, the ingest job is a Lakeflow job like the sweep, and Claude is served through the
workspace's model serving.

## Talking to the agent

| Where | How | When |
| --- | --- | --- |
| Seltzer | A side panel on every screen, plus "Ask the agent" on a card | M1 |
| Email | Forward or CC a team mailbox (for example `seltzer@company`); the agent replies by email | M2 |
| Teams | A Seltzer bot in chats and channels | M2. Needs a small relay, because the Apps sign-in proxy stands between Teams and the app (spike) |

## What the agent can do

The agent's tools are Seltzer's own domain functions, generated from the same Pydantic schemas as
the REST API. The UI, the API, a future MCP server and the agent all share one surface. How much it
may do on its own depends on who started the work.

| Tool | Started by a person in conversation | Started by email or Teams content |
| --- | --- | --- |
| Read: search cards, read a card, board summary, timeline, who is working on what | Yes, within that person's access | Yes, within the mailbox owner's access |
| Create a draft card (private to the person) | Yes | Yes. This is the main output of ingestion |
| Link a signal to a card, suggest an owner, flag a likely duplicate | Yes | Yes, as suggestions on the draft |
| Comment, add steps, add tags | Yes, shown in the conversation and undoable | Proposal only |
| Move, postpone, close, reopen, assign | Yes, if the person could, with a one-tap confirm | Proposal only |
| Change a team's columns, fields, rules or views | Proposal only, accepted by a board admin | Never |

Every write goes through `activity.record()` with the agent as the actor. The agent does not float
cards to the top unless the change is real work on the card. This uses the "mod changes don't touch
cards" rule from [docs/mods.md](mods.md).

## Context from email and Teams

**What it reads**

- **Email:** the person's inbox, or folders they choose. Uses the delegated Microsoft Graph
  `Mail.Read` permission.
- **Teams:** chats the person is in (delegated `Chat.Read`), and channels the person picks
  (delegated `ChannelMessage.Read.All`, which needs admin consent).

It does not use Microsoft's tenant-wide export APIs (`getAllMessages`). Those take application
permissions over every mailbox and chat and are intended for compliance tools
([Teams API licensing](https://learn.microsoft.com/en-us/graph/teams-licenses)).

**How it reads**

Each person connects their Microsoft account once, through an Entra app registration with those
delegated scopes. Their refresh token is stored encrypted, with the key held in a Databricks
secret scope, and disconnecting deletes it.

An ingest job polls each connected person's Graph delta links every few minutes. It polls rather
than receiving Graph push notifications, because those would have to reach the app through its
sign-in proxy (spike).

**What it keeps**

- **The signal:** one `signals` row per message that looks like work. It holds the source, a link
  back, the sender, the time, the subject and a short excerpt. Seltzer never copies the mailbox.
  The agent fetches the full text on demand, with the owner's token.
- **Who sees it:** a signal belongs to the person whose mailbox or chat it came from. It reaches a
  board only when that person publishes a draft card that links it.
- **Retention:** signals never linked to a card are deleted after 30 days (proposed).

**Screening**

A first pass decides whether a message is work worth a draft card: a request, a bug, a decision, a
deadline. Most mail is not. Drafts land in the person's Maybe? with a summary, the suggested board,
owner and duplicates, and a link back to the thread. Seltzer's existing drafts are private to
their author, which is exactly the visibility this needs.

## Shaping each team's workflow

A team can ask the agent to set its board up: "we triage customer escalations from email and
promise a reply in two days", for instance. The agent proposes a **change set**: columns, fields,
rules and saved views, previewed on the board. A board admin accepts it, and it is recorded as
events, so the whole set can be reverted in one step.

Change sets are built from data, not code:

- columns
- fields and rules, using the `after`, `schedule` and `fields` hooks from
  [docs/mods.md](mods.md)
- saved views, assembled from a fixed kit of UI components

The agent never generates free-form UI code. Every team's board stays recognisably Seltzer, and
nothing it adds can break the board.

## The model and the loop

- **Model:** Claude Opus 5.5 (`claude-opus-5-5`) with adaptive thinking. Set the effort explicitly
  (its default is `medium`): `low` for quick chat and screening, `high` for planning and change
  sets. Whether a cheaper model should screen high-volume email is a cost decision to make after
  measuring.
- **Where it is served:** through the Anthropic Python SDK pointed at Databricks model serving's
  Anthropic Messages API (beta), so prompts and data stay under the workspace's governance
  ([Databricks docs](https://docs.databricks.com/aws/en/machine-learning/model-serving/query-anthropic-messages)).
  Which Claude models the workspace can serve is a spike; the fallback is the Anthropic API
  directly.
- **The loop:** hosted in the Seltzer backend, using the Messages API with tools. The tools must run
  as the requesting person inside the app, and the spec keeps everything inside the workspace.
  Anthropic's hosted agents (Managed Agents) would run the loop outside the workspace, so they are
  not proposed.
- **Robustness:**
  - Tool schemas are strict.
  - Ingested text is passed as tool results, never as instructions.
  - A refusal stop reason gets a polite "I can't help with that" rather than a silent failure.
  - Every run is a session row whose state the UI shows.

## Data model additions

| Table | Purpose |
| --- | --- |
| `users.kind` | `person` or `agent`, so the agent appears in stamps, timelines and filters |
| `card_delegates` | The agent working on a card on behalf of its assignee |
| `agent_sessions` | One row per piece of work: who started it, card or board, state, timestamps |
| `agent_messages` | The conversation and tool calls of a session, for the panel and for audit |
| `microsoft_connections` | Per-person Graph connection: scopes, encrypted refresh token, delta links |
| `signals`, `card_signals` | Ingested messages, and their links to cards |
| `change_sets` | Proposed workflow changes: contents, status, who accepted, events produced |

## Milestones

1. **M1: the agent in Seltzer.**
   - **Scope:** side panel, agent identity and delegation, visible sessions, and tools over today's
     domain functions. The agent can answer questions from the event log, create and triage cards,
     and move them with a confirm. No outside context yet.
   - **Done when** a person can say "plan my week from my open cards" and "move the login bug to
     Review", and get it.
2. **M2: email and Teams.**
   - **Scope:** Microsoft connection, the ingest job, signals, screening into private draft cards,
     the team mailbox, and the Teams bot behind its relay.
   - **Done when** a request sent by email or in a Teams chat shows up as a draft in the right
     person's Maybe? within minutes, with a link back and no other person able to see it.
3. **M3: team setup by conversation.**
   - **Scope:** change sets built on the first hooks from [docs/mods.md](mods.md) (`after`,
     `schedule`, `fields`) and saved views.
   - **Done when** a team can describe its process and accept a working board setup without
     anyone editing settings by hand.

## Spikes

- **Claude on Databricks:** which Claude models the workspace's model serving offers through the
  Anthropic Messages API, and whether streaming, strict tools and refusal fallbacks work there.
- **Databricks user authorization:** the agent's reads and writes in Seltzer can use the person's
  identity, but user tokens expire, so background ingestion needs another identity.
- **Microsoft Graph in your tenant:**
  - an Entra app registration
  - admin consent for `ChannelMessage.Read.All`
  - storing refresh tokens under company policy
  - delta query behaviour for chats
- **Reaching the app from outside:** whether Teams bot traffic or Graph notifications can reach a
  Databricks App, or need a relay (for example a small Azure Function holding a service-principal
  token).
- **Prompt injection:** a test set of hostile emails, run before M2 ships.

## Open decisions

1. **What may the agent do without asking?** Assumed above: from conversation, what the person
   could do, with a confirm for moves; from email and Teams, drafts and proposals only.
2. **Team mailbox or personal mailboxes first?** The team mailbox needs one consent and is easier
   to govern. Personal mailboxes catch more but need every person to connect.
3. **Retention of unlinked signals:** 30 days is proposed.
