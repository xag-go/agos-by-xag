import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  getAccountLimits,
  getBackupStatus,
  getFlags,
  getErrorIssues,
  getNotificationRules,
  getPushDevices,
  getUsagePrefs,
  getOwnerName,
  getOwnerTimezone,
  getBrain,
  getOwnerRules,
  getHermesLimits,
  getHermesTimeLimits,
  getHermesFallback,
  getHermesHelperModels,
  getHermesVoice,
  getHermesAllSettings,
  getKeyPools,
  getAppFacts,
  getModelCatalog,
  getCofounderActionsMode,
  getTabsOrder,
  getArchivedWorkspaces,
  getTrashedWorkspaces,
  getConnectorCatalog,
  getLibrary,
  getProviders,
  getWorkspaces,
} from "@/data/queries";
import { cookies } from "next/headers";
import { AccessSettings } from "@/features/settings/access-settings";
import { parseTheme, themeCookie } from "@/features/theme/theme";
import { Suspense } from "react";
import { ArchiveAndTrash } from "@/features/settings/archive-and-trash";
import {
  settingsSections,
  type SettingsSlug,
} from "@/features/settings/sections";
import {
  OwnerRules,
  GeneralSettings,
  HermesSettingsPage,
  HelperModelsPage,
  KeyPoolsCard,
  HermesHealthView,
  SecretsCheckView,
  ModelsSettings,
  LibraryList,
  GithubTokenCard,
  ConnectorsCatalog,
  NotificationsSettings,
  PushDevices,
  ServerSettings,
  UsageLimits,
  ErrorsView,
} from "@/features/settings/lazy-sections";

export function generateStaticParams() {
  return settingsSections.map((s) => ({ section: s.slug }));
}

export const dynamicParams = false;
export const dynamic = "force-dynamic";

function findSection(slug: string) {
  return settingsSections.find((s) => s.slug === slug);
}

export async function generateMetadata({
  params,
}: PageProps<"/settings/[section]">): Promise<Metadata> {
  const { section } = await params;
  return { title: findSection(section)?.label ?? "Settings" };
}

export default async function SettingsSectionPage({
  params,
}: PageProps<"/settings/[section]">) {
  const { section } = await params;
  const meta = findSection(section);
  if (!meta) notFound();

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="font-display text-xl font-semibold">{meta.label}</h2>
        <p className="mt-1 max-w-2xl text-sm text-ink-2">{meta.description}</p>
      </div>
      {/* The heading shows at once; the section's reads (some are Hermes-backed
          and slow when cold) stream in behind it. */}
      <Suspense key={meta.slug} fallback={<SectionLoading />}>
        <SectionBody slug={meta.slug} />
      </Suspense>
    </div>
  );
}

/** The section's place while its data is on the way. */
function SectionLoading() {
  return (
    <div
      role="status"
      aria-label="Loading"
      className="flex animate-pulse flex-col gap-4 motion-reduce:animate-none"
    >
      <div className="h-24 rounded-2xl bg-sunken" />
      <div className="grid gap-4 md:grid-cols-2">
        <div className="h-32 rounded-2xl bg-sunken" />
        <div className="h-32 rounded-2xl bg-sunken" />
      </div>
    </div>
  );
}

/** The workspaces as the pickers show them. */
async function workspaceNames() {
  return (await getWorkspaces()).map((w) => ({ id: w.id, name: w.name }));
}

// Each section asks the core for all it shows at once (one wait, not one per read).
async function SectionBody({ slug }: { slug: SettingsSlug }) {
  switch (slug) {
    case "general": {
      const [
        jar,
        tabs,
        cofounder,
        { timezone },
        { name: ownerName },
        hermesLimits,
        hermesTimeLimits,
        hermesFallback,
        hermesVoice,
        modelCatalog,
        flags,
      ] = await Promise.all([
        cookies(),
        getTabsOrder(),
        getCofounderActionsMode(),
        getOwnerTimezone(),
        getOwnerName().catch(() => ({ name: "" })),
        getHermesLimits(),
        getHermesTimeLimits(),
        getHermesFallback(),
        getHermesVoice(),
        getModelCatalog(),
        getFlags().catch(() => []),
      ]);
      return (
        <GeneralSettings
          theme={parseTheme(jar.get(themeCookie)?.value)}
          tabs={tabs.order}
          cofounderMode={cofounder.mode}
          timezone={timezone}
          ownerName={ownerName}
          hermesLimits={hermesLimits}
          hermesTimeLimits={hermesTimeLimits}
          hermesFallback={hermesFallback}
          hermesVoice={hermesVoice}
          modelCatalog={modelCatalog}
          flags={flags}
        />
      );
    }
    case "rules": {
      const [rules, workspaces] = await Promise.all([
        getOwnerRules(),
        workspaceNames(),
      ]);
      return <OwnerRules rules={rules} workspaces={workspaces} />;
    }
    case "brain": {
      const [rules, workspaces] = await Promise.all([
        getBrain(),
        workspaceNames(),
      ]);
      return <OwnerRules kind="brain" rules={rules} workspaces={workspaces} />;
    }
    case "models": {
      const [providers, pools, catalog] = await Promise.all([
        getProviders(),
        getKeyPools(),
        getModelCatalog(),
      ]);
      return (
        <div className="flex flex-col gap-8">
          <ModelsSettings providers={providers} />
          <KeyPoolsCard pools={pools} catalog={catalog} />
        </div>
      );
    }
    case "helper-models": {
      const [data, catalog] = await Promise.all([
        getHermesHelperModels(),
        getModelCatalog(),
      ]);
      return <HelperModelsPage data={data} catalog={catalog} />;
    }
    case "tools": {
      const [items, workspaces] = await Promise.all([
        getLibrary("tool"),
        getWorkspaces(),
      ]);
      return (
        <div className="flex flex-col gap-6">
          <LibraryList
            kind="tool"
            items={items}
            workspaces={workspaces}
            catalog={[]}
          />
          <GithubTokenCard />
        </div>
      );
    }
    case "connectors": {
      const [apps, servers, workspaces] = await Promise.all([
        getConnectorCatalog(),
        getLibrary("mcp"),
        getWorkspaces(),
      ]);
      return (
        <ConnectorsCatalog
          apps={apps}
          servers={servers}
          workspaces={workspaces}
        />
      );
    }
    case "hermes": {
      const [data, catalog, workspaces] = await Promise.all([
        getHermesAllSettings(),
        getModelCatalog(),
        workspaceNames(),
      ]);
      return (
        <Suspense>
          <HermesSettingsPage
            data={data}
            catalog={catalog}
            workspaces={workspaces}
          />
        </Suspense>
      );
    }
    case "health":
      return (
        <div className="flex max-w-4xl flex-col gap-6">
          <HermesHealthView />
          <SecretsCheckView />
        </div>
      );
    case "errors": {
      const [data, workspaces] = await Promise.all([
        getErrorIssues(),
        workspaceNames(),
      ]);
      return <ErrorsView data={data} workspaces={workspaces} />;
    }
    case "usage": {
      const [limits, prefs] = await Promise.all([
        getAccountLimits(),
        getUsagePrefs(),
      ]);
      return <UsageLimits limits={limits} prefs={prefs} />;
    }
    case "notifications": {
      const [rules, devices] = await Promise.all([
        getNotificationRules(),
        getPushDevices(),
      ]);
      return (
        <div className="flex max-w-3xl flex-col gap-6">
          <PushDevices devices={devices} />
          <NotificationsSettings rules={rules} />
        </div>
      );
    }
    case "access":
      return <AccessSettings />;
    case "server": {
      const [archived, trashed, facts, status] = await Promise.all([
        getArchivedWorkspaces(),
        getTrashedWorkspaces(),
        getAppFacts(),
        getBackupStatus(),
      ]);
      return (
        <div className="flex max-w-3xl flex-col gap-6">
          <ArchiveAndTrash
            archived={archived}
            trashed={trashed}
            trashDays={facts?.trashDays ?? null}
          />
          <ServerSettings status={status} />
        </div>
      );
    }
  }
}
