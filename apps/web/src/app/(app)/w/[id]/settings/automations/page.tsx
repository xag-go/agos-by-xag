import { redirect } from "next/navigation";

/** Automations moved to their own workspace tab. */
export default async function OldAutomations({
  params,
  searchParams,
}: PageProps<"/w/[id]/settings/automations">) {
  const { id } = await params;
  const query = new URLSearchParams();
  for (const [k, v] of Object.entries(await searchParams))
    if (typeof v === "string") query.set(k, v);
  const rest = query.size ? `?${query.toString()}` : "";
  redirect(`/w/${encodeURIComponent(id)}/automations${rest}`);
}
