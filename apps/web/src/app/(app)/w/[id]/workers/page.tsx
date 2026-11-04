import { redirect } from "next/navigation";

/** Workers is now two tabs, Hierarchy and Messages; old links keep working. */
export default async function OldWorkersPage({
  params,
}: PageProps<"/w/[id]/workers">) {
  const { id } = await params;
  redirect(`/w/${encodeURIComponent(id)}/hierarchy`);
}
