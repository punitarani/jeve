---
id: "WEB-0007"
title: "Reports keep the field report’s own look, and a published report is frozen data"
status: "accepted"
date: 2026-09-23
deciders: ["claude"]
scope: ["apps/web/src/components/report/**", "apps/web/src/reports/**", "apps/web/src/app/reports/**", "apps/web/e2e/reports.spec.ts"]
tags: ["web", "reports", "ui", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["WEB-0005", "WEB-0006", "API-0003"]
confirmation: "pnpm --filter @jeve/web exec tsc --noEmit"
---
# WEB-0007 — Reports keep the field report's own look, and a published report is frozen data

## Context and Problem Statement

The first field report ("Day 1 in Prod") was published as a standalone
artifact: its own palette tokens, three typefaces, hand-drawn SVG charts, and
a canvas town. The site needed it reproduced exactly at `/reports/<slug>`, and a
live report at `/reports` in the same style. WEB-0006 says generic chrome is
shadcn, and a reasonable engineer would port the report onto `Card`, `Table`,
`Select` and a charting library. That would be a different report.

## Considered Options

- **A report kit that is the artifact's markup and charts, in React, under a
  scoped stylesheet, shared by every report** — taken.
- **shadcn primitives and a charting library** — rejected: end labels in place
  of legends, speech-bubble annotations, a crosshair that reads every series
  at once, the pixel headings: the look *is* the report, and none of it is
  generic chrome.
- **Embedding the published HTML in an iframe** — rejected: exact, but a
  second site inside the first, with nothing shared with the live report.
- **Publishing reports from the API or a database table** — rejected: a
  report's prose is written against its numbers, so the two are frozen
  together; a table would make them independently editable.

## Decision Outcome

Report pages render through `components/report/`: the artifact's markup, its
four chart forms and its town, ported to React over data props, styled by
`report.css` scoped under `.rpt`, and set in its own typefaces (loaded by a
stylesheet link, not `next/font`, for WEB-0006's reason).

A published report is a directory under `src/reports/<slug>/`: its data as
extracted, and a component holding its prose. `src/reports/index.ts` lists
them, and the static export pre-renders one page per entry (WEB-0005). The
live report is the same components over `GET /report` (API-0003), with
rule-based findings where the published one has a reader's.

This is an exception to WEB-0006 for report pages only. The dashboard and the
world view keep shadcn.

### Consequences

- Good: the published report is reproduced exactly, and the live one cannot
  drift from it in look, because they are the same components.
- Bad: a second small component vocabulary (chips, sortable table, native
  select) beside shadcn's, and three web fonts on report pages.
- What would reverse it: report pages needing the dashboard's interaction
  primitives (menus, dialogs). Then those pieces should be shadcn, restyled
  by `.rpt`, rather than grown by hand.
