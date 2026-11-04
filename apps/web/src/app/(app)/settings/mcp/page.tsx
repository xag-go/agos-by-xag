import { redirect } from "next/navigation";

/** The shared list of apps and MCP servers is Settings → Connectors. */
export default function OldMcp() {
  redirect("/settings/connectors");
}
