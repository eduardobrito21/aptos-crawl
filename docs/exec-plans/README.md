# Execution plans

Plans are first-class artifacts. Each meaningful piece of work gets a
plan, checked into the repo, updated as work progresses.

## Layout

- **`active/`** — plans for in-flight or upcoming work, numbered by
  intended order (`NNNN-kebab-case.md`). Update as you learn; never let a
  plan get out of sync with reality.
- **`completed/`** — plans that have been finished. Read-only after
  move; useful as a historical record of how problems were actually
  solved.

## Format

Every plan has these sections:

- **Status** — `Not started` / `In progress` / `Complete` / `Inactive`.
  Always current.
- **Goal** — one paragraph. What changes when this is done.
- **Out of scope** — explicit non-goals. What this plan will *not* do.
- **Steps** — ordered list. Each step is small enough to verify
  individually.
- **Definition of done** — falsifiable test(s) that must pass for the
  plan to move to `completed/`.
- **Open questions** — things you don't know yet. Resolve before
  starting; convert to ADRs if they're load-bearing.
- **Decision log** — append-only record of decisions made *during*
  execution. Date-stamped.

## Lifecycle

1. Write the plan in `active/`.
2. Begin execution. Update **Status** to `In progress`.
3. As you work, append to **Decision log** for any non-obvious choice.
4. When **Definition of done** is satisfied, move the file to
   `completed/`. Do not edit it after the move.
5. If a plan is abandoned, move it to `completed/` with **Status**
   `Withdrawn` and a note explaining why.

## Inactive plans

Some plans live in `active/` but are gated on an external trigger (an
ADR being flipped, a dependency being available). They use **Status:
Inactive** with a `Trigger:` line at the top stating what would activate
them. Example: `0007-llm-enrichment.md` is Inactive until ADR-009's
acceptance criteria are met and `enrichment.llm: true` is flipped on.
