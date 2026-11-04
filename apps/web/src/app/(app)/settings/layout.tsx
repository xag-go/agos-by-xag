import { SettingsNav } from "@/features/settings/settings-nav";

export default function SettingsLayout({ children }: LayoutProps<"/settings">) {
  return (
    <div className="settings-page flex min-w-0 flex-col gap-6">
      <h1 className="font-display text-3xl font-semibold tracking-tight">
        Settings
      </h1>
      <div className="grid gap-8 md:grid-cols-[12rem_1fr]">
        <SettingsNav />
        <div className="min-w-0">{children}</div>
      </div>
    </div>
  );
}
