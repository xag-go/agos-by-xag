import type { Worker } from "@/data/types";

/** A hire's kit (step 62, engine/hire_kit.py): what the member needs to do
 * its work well. */
export type KitTool = {
  name: string;
  why?: string;
  connector?: string;
  key?: string;
  alternative?: string;
};
export type KitSkill = {
  name: string;
  source?: "library" | "find" | "write";
  why?: string;
};
export type KitDoc = {
  title?: string;
  path?: string;
  url?: string;
  kind?: "doc" | "example";
};
export type Kit = {
  tools?: KitTool[];
  skills?: KitSkill[];
  docs?: KitDoc[];
  team?: { works_with?: string[]; project?: string };
  onboarding?: { task?: string; criteria?: string[] };
};

/** The kit as it is sent: blank rows and blank criteria dropped. */
export function sentKit(kit: Kit): Kit {
  return {
    ...kit,
    tools: (kit.tools ?? []).filter((t) => t.name.trim()),
    skills: (kit.skills ?? []).filter((s) => s.name.trim()),
    docs: (kit.docs ?? []).filter((d) => (d.path || d.url || "").trim()),
    onboarding: {
      task: kit.onboarding?.task ?? "",
      criteria: (kit.onboarding?.criteria ?? [])
        .map((c) => c.trim())
        .filter(Boolean),
    },
  };
}

/** A member's kit: none (hired before kits) / incomplete / whole. */
export type KitState = NonNullable<Worker["kit"]>;
