import { redirect } from "next/navigation";

/** Settings → Security is Settings → Access now (there is no login to secure). */
export default function OldSecurity() {
  redirect("/settings/access");
}
