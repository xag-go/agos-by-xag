import dynamic from "next/dynamic";

// Each section's client code loads only on its own tab (server-rendered as
// before, so nothing flashes): one bundle with every section was fetched and
// parsed on every Settings tab.
export const OwnerRules = dynamic(() =>
  import("@/features/settings/owner-rules").then((m) => m.OwnerRules),
);
export const GeneralSettings = dynamic(() =>
  import("@/features/settings/general-settings").then((m) => m.GeneralSettings),
);
export const HelperModelsPage = dynamic(() =>
  import("@/features/settings/helper-models").then((m) => m.HelperModelsPage),
);
export const KeyPoolsCard = dynamic(() =>
  import("@/features/settings/key-pools-card").then((m) => m.KeyPoolsCard),
);
export const HermesHealthView = dynamic(() =>
  import("@/features/settings/hermes-health").then((m) => m.HermesHealthView),
);
export const SecretsCheckView = dynamic(() =>
  import("@/features/settings/secrets-check").then((m) => m.SecretsCheckView),
);
export const ModelsSettings = dynamic(() =>
  import("@/features/settings/models-settings").then((m) => m.ModelsSettings),
);
export const LibraryList = dynamic(() =>
  import("@/features/library/library-list").then((m) => m.LibraryList),
);
export const GithubTokenCard = dynamic(() =>
  import("@/features/library/github-token").then((m) => m.GithubTokenCard),
);
export const ConnectorsCatalog = dynamic(() =>
  import("@/features/connectors/connectors-catalog").then(
    (m) => m.ConnectorsCatalog,
  ),
);
export const NotificationsSettings = dynamic(() =>
  import("@/features/settings/other-settings").then(
    (m) => m.NotificationsSettings,
  ),
);
export const PushDevices = dynamic(() =>
  import("@/features/settings/push-devices").then((m) => m.PushDevices),
);
export const ServerSettings = dynamic(() =>
  import("@/features/settings/other-settings").then((m) => m.ServerSettings),
);
export const UsageLimits = dynamic(() =>
  import("@/features/settings/other-settings").then((m) => m.UsageLimits),
);
export const ErrorsView = dynamic(() =>
  import("@/features/settings/errors-view").then((m) => m.ErrorsView),
);
