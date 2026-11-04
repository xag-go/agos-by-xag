import { dateTime } from "@/shared/format";

export const when = (seconds: number) => dateTime(new Date(seconds * 1000));

export const ago = (seconds: number) => {
  const minutes = Math.max(0, Math.round((Date.now() / 1000 - seconds) / 60));
  if (minutes < 60) return `${String(minutes)} min. ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${String(hours)} hr. ago`;
  return `${String(Math.round(hours / 24))} days ago`;
};

export const fmtTokens = (n: number) =>
  n >= 1000
    ? `~${String(Math.round(n / 1000))}k tokens`
    : `~${String(n)} tokens`;

export const eventName = (kind: string) => {
  const text = kind.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
};
