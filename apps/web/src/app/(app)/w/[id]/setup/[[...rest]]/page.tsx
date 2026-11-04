import { redirect } from "next/navigation";

/** Setup moved into Workspace settings; old links keep working. */
export default async function OldSetup({
  params,
}: PageProps<"/w/[id]/setup/[[...rest]]">) {
  const { id, rest } = await params;
  const section = rest?.[0] === "connectors" ? "connectors" : "automations";
  redirect(`/w/${encodeURIComponent(id)}/settings/${section}`);
}
