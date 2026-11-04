import { z } from "zod";
import { WORKSPACE_ID_PATTERN } from "./workspace-id";

/** The server's check of a workspace id (the rule is in ./workspace-id.ts). */
export const workspaceIdSchema = z
  .string()
  .regex(
    WORKSPACE_ID_PATTERN,
    "use lowercase letters, digits and dashes (max 63 chars)",
  );
