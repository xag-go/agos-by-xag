import { redirect } from "next/navigation";

/** Old link: Messages is its own tab now. */
export default async function OldMessagesPage({
  params,
  searchParams,
}: PageProps<"/w/[id]/workers/messages">) {
  const { id } = await params;
  const { c } = await searchParams;
  const query = typeof c === "string" ? `?c=${encodeURIComponent(c)}` : "";
  redirect(`/w/${encodeURIComponent(id)}/messages${query}`);
}
