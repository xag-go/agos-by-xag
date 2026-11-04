import { getRemoteAccess } from "@/data/queries";
import { RemoteAccessCard } from "./remote-access-card";
import { PanelSection } from "@/shared/ui/panel";

/** Settings → Access: who can open AGOS. There is no login: AGOS listens only on
 * this machine, and another device reaches it only through the owner's
 * Tailscale (the card below turns that on). */
export async function AccessSettings() {
  const remote = await getRemoteAccess();
  return (
    <div className="flex max-w-3xl flex-col gap-8">
      <RemoteAccessCard initial={remote} />
      <PanelSection className="flex flex-col gap-3 p-5">
        <h2 className="font-display font-semibold">Who can open AGOS</h2>
        <ul className="flex flex-col gap-2 text-sm text-ink-2">
          <li>
            <span className="font-medium text-ink">This machine</span> — open it
            here, nothing to type.
          </li>
          <li>
            <span className="font-medium text-ink">
              Your other devices, over Tailscale
            </span>{" "}
            — once &ldquo;Use AGOS from other devices&rdquo; is on, and only
            when they are logged in with your Tailscale account (or one you also
            allowed).
          </li>
        </ul>
        <p className="text-sm text-ink-3">Anything else is refused.</p>
      </PanelSection>
    </div>
  );
}
