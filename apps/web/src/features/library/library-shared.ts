import type { LibraryKind } from "@/data/types";

export const NOUN: Record<LibraryKind, string> = {
  skill: "skill",
  agent: "agent",
  mcp: "MCP server",
  plugin: "plugin",
  tool: "tool",
};

export const SKILL_TEMPLATE = `---
name: my-skill
description: When to use this skill, in one sentence.
---

# My skill

1. First step.
2. Second step.
`;

/** A rule file an agent can read, with its numbered sections. */
export type DocChoice = { path: string; sections: string[] };
export type Read = { path: string; section: string; mode: "always" | "demand" };
