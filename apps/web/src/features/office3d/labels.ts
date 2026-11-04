import type { Activity } from "./controller";

// Plain words for each activity. Kept out of ./character (which imports three)
// so the page's header, feed and inspector can show them without loading the
// 3D code first.
export const LABEL: Record<Activity, string> = {
  working: "Working",
  thinking: "Thinking",
  waiting: "Waiting for you",
  blocked: "Blocked",
  meeting: "In a meeting",
  break: "On a break",
  idle: "Free",
  offline: "Offline",
};
