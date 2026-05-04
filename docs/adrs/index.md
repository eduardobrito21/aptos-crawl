# Architecture Decision Records

This directory captures durable decisions about how the pipeline is
built. Each document records **one** decision, the context that drove
it, the alternatives considered, and the consequences accepted.

ADRs are append-only. If a decision is reversed, write a new ADR that
**Supersedes** the old one — do not edit the old one in place.

## Format

Each ADR has these sections:

- **Status** — `Proposed`, `Accepted`, `Superseded by NNN`,
  `Withdrawn`.
- **Date** — when the decision was made.
- **Related** — comma-separated ADR numbers that touch the same area
  (optional, but encouraged).
- **Context** — what made this decision necessary; what was true at
  the time.
- **Decision** — what we chose.
- **Consequences** — positive, negative, and neutral effects.
- **Acceptance criteria** — for `Proposed` ADRs only: the falsifiable
  test(s) that flip the status to `Accepted`.

Filenames are `NNN-kebab-case-summary.md`, three-digit zero-padded.

## Index

| ADR                                          | Title                                                           | Status   |
| -------------------------------------------- | --------------------------------------------------------------- | -------- |
| [001](001-source-priority.md)                | Prioritize ZAP Imóveis as the primary source                    | Accepted |
| [002](002-playwright-sync.md)                | Playwright sync API with persistent context                     | Accepted |
| [003](003-sqlite-source-of-truth.md)         | SQLite as source of truth, Notion as the UI                     | Accepted |
| [004](004-price-history.md)                  | Price history via daily snapshot with dedup                     | Accepted |
| [005](005-quintoandar-risk.md)               | Treat QuintoAndar as a secondary, risky source                  | Accepted |
| [006](006-cross-platform-dedup.md)           | Cross-platform dedup via heuristic fingerprint                  | Proposed |
| [007](007-qualitative-extraction.md)         | Qualitative criteria extraction via keyword matching            | Accepted |
| [008](008-notion-export.md)                  | Idempotent Notion export with manual fields preserved           | Accepted |
| [009](009-llm-enrichment.md)                 | LLM as a complementary enrichment layer                         | Proposed |
| [010](010-google-maps-platform.md)           | Google Maps Platform for commute enrichment                     | Proposed |

## Cross-reference graph

```
001 ←→ 005          source priority ↔ QA risk
002 ←→ 005          Playwright config ↔ QA risk (anti-bot drives design)
003 ←→ 008          SQLite SoT ↔ Notion projection
007 ←→ 009          keyword extraction ↔ LLM as complementary fallback
009 ←→ 010          LLM enrichment ↔ commute (LLM helps with address parsing)
```
