import { redirect } from "next/navigation";

/** Telegram is now one of the workspace's Channels. */
export default async function OldTelegram({
  params,
  searchParams,
}: PageProps<"/w/[id]/settings/telegram">) {
  const { id } = await params;
  const { setup } = await searchParams;
  redirect(
    `/w/${encodeURIComponent(id)}/settings/channels${setup === "qr" ? "?setup=qr" : ""}`,
  );
}
