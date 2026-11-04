// Small line icons drawn for this app (16px grid, currentColor).

const common = {
  viewBox: "0 0 16 16",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  className: "size-4",
  "aria-hidden": true,
};

export const PlusIcon = () => (
  <svg {...common}>
    <path d="M8 3.5v9M3.5 8h9" />
  </svg>
);

export const GearIcon = () => (
  <svg {...common}>
    <path
      d="M12.68 6.95 L14.35 7.17 L14.35 8.83 L12.68 9.05 L12.05 10.57 L13.07 11.90 L11.90 13.07 L10.57 12.05 L9.05 12.68 L8.83 14.35 L7.17 14.35 L6.95 12.68 L5.43 12.05 L4.10 13.07 L2.93 11.90 L3.95 10.57 L3.32 9.05 L1.65 8.83 L1.65 7.17 L3.32 6.95 L3.95 5.43 L2.93 4.10 L4.10 2.93 L5.43 3.95 L6.95 3.32 L7.17 1.65 L8.83 1.65 L9.05 3.32 L10.57 3.95 L11.90 2.93 L13.07 4.10 L12.05 5.43Z"
      strokeWidth={1.3}
    />
    <circle cx="8" cy="8" r="2" />
  </svg>
);

export const MenuIcon = () => (
  <svg {...common}>
    <path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" />
  </svg>
);

/** A panel with its side bar, and a chevron pointing where it will go. */
export const SidebarIcon = ({ open }: { open: boolean }) => (
  <svg {...common}>
    <rect x="2" y="2.5" width="12" height="11" rx="2.5" />
    <path d="M6 2.5v11" />
    <path
      d={open ? "M10.5 6.5L9 8l1.5 1.5" : "M9.5 6.5L11 8l-1.5 1.5"}
      className="transition-[d] duration-300"
    />
  </svg>
);

export const SunIcon = () => (
  <svg {...common}>
    <circle cx="8" cy="8" r="2.6" />
    <path d="M8 1.6v1.4M8 13v1.4M1.6 8h1.4M13 8h1.4M3.5 3.5l1 1M11.5 11.5l1 1M3.5 12.5l1-1M11.5 4.5l1-1" />
  </svg>
);

export const MoonIcon = () => (
  <svg {...common}>
    <path d="M13 9.6A5.3 5.3 0 0 1 6.4 3a5.3 5.3 0 1 0 6.6 6.6z" />
  </svg>
);

export const AutoIcon = () => (
  <svg {...common}>
    <circle cx="8" cy="8" r="5.6" />
    <path d="M8 2.4v11.2a5.6 5.6 0 0 0 0-11.2z" fill="currentColor" />
  </svg>
);

// ---- workspace sections (sidebar) ----

export const DashboardIcon = () => (
  <svg {...common}>
    <rect x="2.5" y="2.5" width="4.5" height="5.5" rx="1" />
    <rect x="9" y="2.5" width="4.5" height="3.5" rx="1" />
    <rect x="2.5" y="10" width="4.5" height="3.5" rx="1" />
    <rect x="9" y="8" width="4.5" height="5.5" rx="1" />
  </svg>
);

export const BoardIcon = () => (
  <svg {...common}>
    <rect x="2.5" y="2.5" width="11" height="11" rx="1.5" />
    <path d="M6.2 2.5v11M9.8 2.5v11" />
  </svg>
);

export const ChatIcon = () => (
  <svg {...common}>
    <path d="M3 3.5h10a.5.5 0 0 1 .5.5v6.5a.5.5 0 0 1-.5.5H7l-3 2.5V11H3a.5.5 0 0 1-.5-.5V4a.5.5 0 0 1 .5-.5z" />
  </svg>
);

export const TeamIcon = () => (
  <svg {...common}>
    <rect x="6" y="2" width="4" height="3" rx="0.8" />
    <rect x="1.8" y="11" width="4" height="3" rx="0.8" />
    <rect x="10.2" y="11" width="4" height="3" rx="0.8" />
    <path d="M8 5v3M3.8 11V8h8.4v3" />
  </svg>
);

/** A target: the workspace goal. */
export const GoalIcon = () => (
  <svg {...common}>
    <circle cx="8" cy="8" r="6" />
    <circle cx="8" cy="8" r="3" />
    <circle cx="8" cy="8" r="0.6" />
  </svg>
);

export const AutomationIcon = () => (
  <svg {...common}>
    <path d="M9 1.8 3.5 9H8l-1 5.2L12.5 7H8z" />
  </svg>
);

export const DocsIcon = () => (
  <svg {...common}>
    <path d="M4 1.8h5.5L12.5 5v9.2H4z" />
    <path d="M9.5 1.8V5h3M6 8h4.5M6 10.5h4.5" />
  </svg>
);

/** A picture frame: the workspace's artifacts (files and documents of its cards). */
export const ArtifactsIcon = () => (
  <svg {...common}>
    <rect x="1.8" y="2.5" width="12.4" height="11" rx="1.2" />
    <path d="M1.8 10.5 5.5 7l3 3 2-2 3.7 3.5" />
    <circle cx="10.5" cy="5.5" r="1" />
  </svg>
);

export const ScreenIcon = () => (
  <svg {...common}>
    <rect x="1.8" y="2.5" width="12.4" height="8.5" rx="1.2" />
    <path d="M6 14h4M8 11v3" />
  </svg>
);

export const LogIcon = () => (
  <svg {...common}>
    <path d="M5.5 4h8M5.5 8h8M5.5 12h8" />
    <circle cx="2.8" cy="4" r=".6" />
    <circle cx="2.8" cy="8" r=".6" />
    <circle cx="2.8" cy="12" r=".6" />
  </svg>
);

/** An inbox tray: what waits for the owner (proposals, asks, questions). */
export const InboxIcon = () => (
  <svg {...common}>
    <path d="M2.5 9.5h3.2l1 1.8h2.6l1-1.8h3.2" />
    <path d="M4 3.5h8l1.5 6v3.5a1 1 0 0 1-1 1h-9a1 1 0 0 1-1-1V9.5z" />
  </svg>
);

/** A wrench: one workspace's own settings (the cog is the general Settings). */
export const WrenchIcon = () => (
  <svg {...common}>
    <path d="M10.2 2.2a3.4 3.4 0 0 0-3.9 4.5L2.4 10.6a1.4 1.4 0 0 0 2 2l3.9-3.9a3.4 3.4 0 0 0 4.5-3.9l-2 2-1.9-.6-.6-1.9z" />
  </svg>
);

/** A pencil: edit. */
export const PencilIcon = () => (
  <svg {...common}>
    <path d="M11.3 2.7a1.5 1.5 0 0 1 2 2L5.5 12.5l-3 .8.8-3zM9.8 4.2l2 2" />
  </svg>
);

/** A bin: delete. */
export const TrashIcon = () => (
  <svg {...common}>
    <path d="M2.5 4.5h11M6 4.5V3h4v1.5M4 4.5l.6 8a1 1 0 0 0 1 .9h4.8a1 1 0 0 0 1-.9l.6-8M6.6 7v4M9.4 7v4" />
  </svg>
);

/** Two people: the team you talk with. */
export const PeopleIcon = () => (
  <svg {...common}>
    <circle cx="6" cy="5.5" r="2.3" />
    <path d="M1.8 13.5c0-2.4 1.9-4 4.2-4s4.2 1.6 4.2 4" />
    <path d="M10.6 3.4a2.2 2.2 0 0 1 0 4.3M12 9.7c1.3.4 2.2 1.8 2.2 3.8" />
  </svg>
);

/** A building: the workspace's Office. */
export const OfficeIcon = () => (
  <svg {...common}>
    <path d="M2.5 14V3.5L9 2v12M9 6h4.5v8M1.5 14h13" />
    <path d="M4.8 5.5h1.6M4.8 8h1.6M4.8 10.5h1.6M11 8.5h1M11 11h1" />
  </svg>
);

/** A magnifier: the workspace search. */
export const SearchIcon = () => (
  <svg {...common}>
    <circle cx="7" cy="7" r="4.5" />
    <path d="m10.5 10.5 3.5 3.5" />
  </svg>
);

/** A card with a pulse line: the status cards (scoped summaries). */
export const StatusIcon = () => (
  <svg {...common}>
    <rect x="1.8" y="2.5" width="12.4" height="11" rx="1.2" />
    <path d="M4 9h2l1.2-2.5 1.6 4 1.2-1.5H12" />
  </svg>
);
