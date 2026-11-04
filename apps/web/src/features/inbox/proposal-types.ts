import type { Kit } from "@/features/workers/kit-types";
import type { HireModel } from "./hire-model";

export type HirePayload = {
  /** A kit for a member already on the team (kind "kit"): that member. */
  member?: string;
  name?: string;
  title?: string;
  role?: string;
  summary?: string;
  model?: HireModel;
  /** Why this model for the role's work (the Co-Founder's line, or the owner's choice). */
  model_why?: string;
  skills?: string[];
  telegram_topic?: boolean;
  coding_engine?: string;
  reports_to?: string;
  why?: string;
  goal_id?: number | null;
  source_card?: string;
  kit?: Kit;
};
export type PlanItem = {
  title: string;
  why?: string;
  member?: string;
  body?: string;
  project_id?: number | null;
};
export type FoundResult = {
  title: string;
  target?: number | null;
  unit?: string;
  due_on?: string;
};
export type FoundProject = { title: string };
export type GoalPayload = {
  change?: string;
  title?: string;
  goal_id?: number | null;
  kr_id?: number | null;
  project_id?: number | null;
  owner?: string;
  status?: string;
  measure?: string;
  why?: string;
  date?: string;
  summary?: string;
  you?: PlanItem[];
  members?: PlanItem[];
  key_results?: FoundResult[];
  projects?: FoundProject[];
  [field: string]: unknown;
};
export type InstructionsPayload = {
  target?: string;
  diff?: string;
  sha256?: string;
  summary?: string;
};
export type PlanPayload = { title?: string; markdown?: string };
/** A hub skill an agent asked for (Step 63): AGOS's own proposal. */
export type SkillPayload = {
  request?: number;
  name?: string;
  source?: string;
  why?: string;
  member?: string;
  scan?: string;
  scripts?: boolean;
  tested?: boolean;
  asked?: string;
};
