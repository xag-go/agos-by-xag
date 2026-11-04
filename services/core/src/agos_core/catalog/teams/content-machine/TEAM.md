---
schema: agos/bundle-v1
kind: team
name: Content Machine
slug: content-machine
description:
  "A content team with a lead: ideas and trends, scripts, edits and posting, planned every
  week."
lead: content-lead
tags:
  - content
  - social
  - video
members:
  - content-lead
  - researcher
  - script-writer
  - video-editor
  - social-media-manager
skills:
  - content-calendar
  - brand-voice
automations:
  - Weekly content plan
  - Trend scan
---

# Content Machine

A content team with a lead: ideas and trends, scripts, edits and posting, planned every week.

## Team

- **Content Lead** (@content-lead), reports to the Co-Founder (or the lead you pick) — Plans the content calendar and keeps the team shipping.
  - **Trend Researcher** (@researcher), reports to @content-lead — Finds trends, references and ideas worth making.
  - **Script Writer** (@script-writer), reports to @content-lead — Writes hooks, scripts and captions in the brand voice.
  - **Video Editor** (@video-editor), reports to @content-lead — Cuts footage into finished reels from the scripts.
  - **Social Media Manager** (@social-media-manager), reports to @content-lead — Schedules posts and reports what worked.

## Skills

- content-calendar — Use when planning a week of content pieces.
- brand-voice — Use when writing anything in the brand's voice.

## Automations

- Weekly content plan — 0 9 * * 1 (@content-lead), installed off: turn it on when ready
- Trend scan — 0 10 * * 1-5 (@researcher), installed off: turn it on when ready

## What you'll be asked for

- OPENROUTER_API_KEY (optional) — Transcribing reels with OpenRouter
