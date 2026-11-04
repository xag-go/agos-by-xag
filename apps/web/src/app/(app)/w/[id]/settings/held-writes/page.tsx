import { redirect } from "next/navigation";

/** Held-back writes now wait in the Inbox (one card per request). */
export default async function Page({
  params,
}: PageProps<"/w/[id]/settings/held-writes">) {
  const { id } = await params;
  redirect(`/w/${encodeURIComponent(id)}/inbox`);
}
