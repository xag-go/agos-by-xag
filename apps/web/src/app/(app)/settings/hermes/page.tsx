import { redirect } from "next/navigation";

/** The old Settings → Hermes settings section is gone
 * (docs/specs/2026-11-04-no-engine-name.md): the curated cards cover the
 * owner's settings and the Co-Founder changes the rest from chat. Old links
 * land on Settings → General. */
export default function GoneToGeneral() {
  redirect("/settings/general");
}
