import { redirect } from "next/navigation";

/** Looking ahead was removed (2026-10-05): its old link opens Automations. */
export default async function Page({
  params,
}: PageProps<"/w/[id]/settings/ahead">) {
  const { id } = await params;
  redirect(`/w/${encodeURIComponent(id)}/automations`);
}
