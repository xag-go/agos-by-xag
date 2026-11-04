"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Select part of any message in the conversation and a small "Reply" button
 * appears just above the selection. Clicking it answers only that part (the
 * agent is told to look at that part, not the whole message).
 *
 * Messages opt in with `data-message-id` (and `data-message-from`, the name
 * shown in the reply bar) on the element that holds their text.
 */
export function SelectionReply({
  container,
  onReply,
}: {
  container: React.RefObject<HTMLElement | null>;
  onReply: (target: { id: number; from: string; excerpt: string }) => void;
}) {
  const [spot, setSpot] = useState<{
    x: number;
    y: number;
    id: number;
    from: string;
    excerpt: string;
  } | null>(null);
  const button = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const root = container.current;
    if (!root) return;
    let frame = 0;
    const read = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const selection = window.getSelection();
        const text = selection?.toString().trim() ?? "";
        if (!selection || selection.rangeCount === 0 || text.length < 2) {
          setSpot(null);
          return;
        }
        const range = selection.getRangeAt(0);
        const start = closestMessage(range.startContainer);
        const end = closestMessage(range.endContainer);
        // Only inside one message of this conversation.
        if (!start || start !== end || !root.contains(start)) {
          setSpot(null);
          return;
        }
        const id = Number(start.dataset.messageId);
        if (!Number.isFinite(id) || id <= 0) {
          setSpot(null);
          return;
        }
        const rect = range.getBoundingClientRect();
        setSpot({
          x: rect.left + rect.width / 2,
          y: rect.top,
          id,
          from: start.dataset.messageFrom ?? "the agent",
          excerpt: text.slice(0, 4000),
        });
      });
    };
    const hideOnScroll = () => {
      setSpot(null);
    };
    document.addEventListener("selectionchange", read);
    root.addEventListener("scroll", hideOnScroll, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("selectionchange", read);
      root.removeEventListener("scroll", hideOnScroll);
    };
  }, [container]);

  if (!spot) return null;
  return (
    <button
      ref={button}
      type="button"
      // Keep the selection while clicking.
      onMouseDown={(e) => {
        e.preventDefault();
      }}
      onClick={() => {
        onReply({ id: spot.id, from: spot.from, excerpt: spot.excerpt });
        window.getSelection()?.removeAllRanges();
        setSpot(null);
      }}
      style={{ left: spot.x, top: spot.y }}
      className="fixed z-50 flex -translate-x-1/2 -translate-y-[calc(100%+8px)] items-center gap-1.5 rounded-full bg-ink px-3 py-1.5 text-xs font-medium text-paper shadow-float transition-transform duration-150 hover:scale-105 active:scale-95"
    >
      <svg viewBox="0 0 16 16" className="size-3.5" fill="none" aria-hidden>
        <path
          d="M6.5 3.5 2.5 7.5l4 4M3 7.5h6.5a4 4 0 0 1 4 4v1"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      Reply to this part
      <span
        aria-hidden
        className="absolute top-full left-1/2 size-2 -translate-x-1/2 -translate-y-1 rotate-45 bg-ink"
      />
    </button>
  );
}

function closestMessage(node: Node): HTMLElement | null {
  const el = node instanceof HTMLElement ? node : node.parentElement;
  return el?.closest<HTMLElement>("[data-message-id]") ?? null;
}
