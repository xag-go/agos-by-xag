import { redirect } from "next/navigation";

/** Renamed: Connectors → Capabilities (old links keep working). */
export default async function OldConnectorsPage({
  params,
}: PageProps<"/w/[id]/settings/connectors">) {
  const { id } = await params;
  redirect(`/w/${encodeURIComponent(id)}/settings/capabilities`);
}
