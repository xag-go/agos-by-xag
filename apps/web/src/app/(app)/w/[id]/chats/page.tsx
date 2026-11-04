import { redirect } from "next/navigation";

/** Chats are now "Sessions"; old links keep working. */
export default async function OldChatsPage({
  params,
  searchParams,
}: PageProps<"/w/[id]/chats">) {
  const { id } = await params;
  const { chat } = await searchParams;
  const query =
    typeof chat === "string" ? `?chat=${encodeURIComponent(chat)}` : "";
  redirect(`/w/${encodeURIComponent(id)}/sessions${query}`);
}
