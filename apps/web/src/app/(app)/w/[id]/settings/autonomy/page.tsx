import { redirect } from "next/navigation";

/** Autonomy now lives on the General settings page, next to Agent access. */
export default async function Page({
  params,
}: PageProps<"/w/[id]/settings/autonomy">) {
  const { id } = await params;
  redirect(`/w/${encodeURIComponent(id)}/settings#autonomy`);
}
