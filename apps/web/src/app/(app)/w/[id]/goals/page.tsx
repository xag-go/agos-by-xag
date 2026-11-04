import { redirect } from "next/navigation";

/** The Goals tab became the Vision page (step 53): old links land there. */
export default async function GoalsRoute({
  params,
}: PageProps<"/w/[id]/goals">) {
  const { id } = await params;
  redirect(`/w/${encodeURIComponent(id)}/vision`);
}
