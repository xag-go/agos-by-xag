/** The workspace tabs AGOS knows; the owner picks their order in Settings → General. */
export const TAB_SECTIONS: Record<string, { path: string; label: string }> = {
  dashboard: { path: "", label: "Dashboard" },
  office: { path: "/office", label: "Office" },
  kanban: { path: "/kanban", label: "Kanban" },
  inbox: { path: "/inbox", label: "Inbox" },
  sessions: { path: "/sessions", label: "Sessions" },
  hierarchy: { path: "/hierarchy", label: "Hierarchy" },
  vision: { path: "/vision", label: "Vision" },
  status: { path: "/status", label: "Status" },
  messages: { path: "/messages", label: "Team Chat" },
  automations: { path: "/automations", label: "Automations" },
  docs: { path: "/docs", label: "Documentation" },
  artifacts: { path: "/artifacts", label: "Artifacts" },
  screen: { path: "/screen", label: "Screen" },
  log: { path: "/log", label: "Log" },
  search: { path: "/search", label: "Search" },
};
