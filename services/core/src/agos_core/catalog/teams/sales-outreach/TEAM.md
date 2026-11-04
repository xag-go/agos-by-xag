---
schema: agos/bundle-v1
kind: team
name: Sales & Outreach
slug: sales-outreach
description:
  Find the right prospects, write to them like a person, and keep the pipeline moving every
  week.
lead: sales-lead
tags:
  - sales
  - outreach
members:
  - sales-lead
  - prospect-researcher
  - outreach-writer
skills:
  - outreach-sequence
automations:
  - Weekly pipeline review
---

# Sales & Outreach

Find the right prospects, write to them like a person, and keep the pipeline moving every week.

## Team

- **Sales Lead** (@sales-lead), reports to the Co-Founder (or the lead you pick) — Owns the pipeline and the weekly targets.
  - **Prospect Researcher** (@prospect-researcher), reports to @sales-lead — Builds lists of the right people, with a reason for each.
  - **Outreach Writer** (@outreach-writer), reports to @sales-lead — Writes short, personal first messages and follow-ups.

## Skills

- outreach-sequence — Use when writing outreach and its follow-ups.

## Automations

- Weekly pipeline review — 0 9 * * 1 (@sales-lead), installed off: turn it on when ready

## What you'll be asked for

- HUBSPOT_ACCESS_TOKEN (optional) — Your CRM, so the team can read and update contacts
