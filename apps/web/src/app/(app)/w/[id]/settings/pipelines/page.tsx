import { redirect } from "next/navigation";

/** Rules moved to Automations (2026-10-28): the old link opens them there. */
export default async function Page({
  params,
}: PageProps<"/w/[id]/settings/pipelines">) {
  const { id } = await params;
  redirect(`/w/${encodeURIComponent(id)}/automations#rules`);
}
