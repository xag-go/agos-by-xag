/** One file ready to send (base64 + a local preview for the message bubble). */
export type DraftFile = {
  key: string;
  kind: "image" | "audio" | "file";
  name: string;
  mime: string;
  size: number;
  data: string;
  preview?: string;
  duration?: number;
};
export type Draft = { text: string; files: DraftFile[]; replyTo?: ReplyTarget };

/** The message the owner is answering (shown above the box, sent with it). */
export type ReplyTarget = {
  id: number;
  from: string;
  preview: string;
  /** Only this selected part of the message is answered. */
  excerpt?: string;
};

/** "20 MB" from bytes. */
export function megabytes(bytes: number): string {
  return `${String(Math.round(bytes / (1024 * 1024)))} MB`;
}

/** The "@abc" being typed right before the caret, if any. */
export function mentionAt(
  text: string,
  caret: number,
): { start: number; query: string } | null {
  const match = /(^|\s)@([\w.-]{0,40})$/.exec(text.slice(0, caret));
  const query = match?.[2];
  if (query === undefined) return null;
  return { start: caret - query.length - 1, query: query.toLowerCase() };
}
