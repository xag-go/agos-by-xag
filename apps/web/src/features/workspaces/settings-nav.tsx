"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/shared/ui/cn";

type Item = { href: string; label: string };

/** Workspace settings sections: General, Identity, Work hours, Review, Labels, Pipelines,
 * Channels, Capabilities, Skills that grow, Keys, Connections, Export / Import. The memory and
 * skill changes Hermes holds for the owner wait in the Inbox. */
export function SettingsNav({ workspaceId }: { workspaceId: string }) {
  const pathname = usePathname();
  const base = `/w/${workspaceId}/settings`;
  const link = (item: Item) => (
    <NavLink key={item.href} item={item} base={base} pathname={pathname} />
  );
  return (
    <nav
      aria-label="Workspace settings"
      className="flex gap-1 overflow-x-auto md:sticky md:top-[calc(var(--ws-header-h,0px)+1.5rem)] md:max-h-[calc(100dvh-var(--ws-header-h,0px)-3rem)] md:flex-col md:self-start md:overflow-y-auto"
    >
      {[
        { href: base, label: "General" },
        { href: `${base}/identity`, label: "Identity & memory" },
        { href: `${base}/learned`, label: "What I learned" },
        { href: `${base}/work-hours`, label: "Work hours" },
        { href: `${base}/review`, label: "Review" },
        { href: `${base}/labels`, label: "Labels" },
        { href: `${base}/channels`, label: "Channels" },
        { href: `${base}/capabilities`, label: "Capabilities" },
        { href: `${base}/skill-growth`, label: "Skills that grow" },
        { href: `${base}/keys`, label: "Keys" },
        { href: `${base}/connections`, label: "Connections" },
        { href: `${base}/export`, label: "Export / Import" },
      ].map(link)}
    </nav>
  );
}

function NavLink({
  item,
  base,
  pathname,
}: {
  item: Item;
  base: string;
  pathname: string;
}) {
  const active =
    item.href === base ? pathname === base : pathname.startsWith(item.href);
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "rounded-lg px-3 py-2 text-sm whitespace-nowrap",
        active
          ? "bg-sunken font-medium text-ink"
          : "text-ink-2 hover:bg-sunken/60 hover:text-ink",
      )}
    >
      {item.label}
    </Link>
  );
}
