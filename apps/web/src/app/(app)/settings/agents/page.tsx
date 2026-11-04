import { redirect } from "next/navigation";
import { getWorkspaces } from "@/data/queries";

/** Agents moved into each workspace (Hierarchy): they belong to one project. */
export default async function AgentsMoved() {
  const first = (await getWorkspaces())[0];
  redirect(first ? `/w/${first.id}/hierarchy` : "/");
}
