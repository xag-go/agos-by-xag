"use client";

import { Fragment, useState, type ReactNode } from "react";
import { cn } from "@/shared/ui/cn";
import { MarkdownLink } from "@/shared/ui/link-chips";

/*
 * A small, safe Markdown renderer for agent answers: it builds React elements
 * (never raw HTML), so nothing in a reply can run script or inject markup.
 * Links open only http(s) and mailto. Covers what agents write: headings,
 * paragraphs, lists, quotes, tables, fenced code (with copy), inline code,
 * bold, italic, strikethrough, links.
 */

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "code"; lang: string; code: string }
  | { kind: "list"; ordered: boolean; start: number; items: string[] }
  | { kind: "quote"; text: string }
  | { kind: "table"; head: string[]; rows: string[][]; align: Align[] }
  | { kind: "rule" };

type Align = "left" | "center" | "right" | null;

const FENCE = /^\s*(```|~~~)\s*([\w+#.-]*)\s*$/;
const HEADING = /^(#{1,6})\s+(.*)$/;
const BULLET = /^\s*[-*+]\s+(.*)$/;
const NUMBERED = /^\s*(\d{1,9})[.)]\s+(.*)$/;
const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/;
const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

function cells(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim());
}

export function parseBlocks(source: string): Block[] {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i] ?? "";
    if (!line.trim()) {
      i++;
      continue;
    }
    const fence = FENCE.exec(line);
    if (fence) {
      const close = fence[1] ?? "```";
      const body: string[] = [];
      i++;
      while (i < lines.length && !(lines[i] ?? "").trim().startsWith(close)) {
        body.push(lines[i] ?? "");
        i++;
      }
      i++; // closing fence (or end of text while streaming)
      blocks.push({
        kind: "code",
        lang: fence[2] ?? "",
        code: body.join("\n"),
      });
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      blocks.push({
        kind: "heading",
        level: heading[1]?.length ?? 1,
        text: heading[2] ?? "",
      });
      i++;
      continue;
    }
    if (RULE.test(line)) {
      blocks.push({ kind: "rule" });
      i++;
      continue;
    }
    if (line.includes("|") && TABLE_SEP.test(lines[i + 1] ?? "")) {
      const head = cells(line);
      const align = cells(lines[i + 1] ?? "").map((c): Align => {
        const l = c.startsWith(":");
        const r = c.endsWith(":");
        return l && r ? "center" : r ? "right" : l ? "left" : null;
      });
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && (lines[i] ?? "").includes("|")) {
        rows.push(cells(lines[i] ?? ""));
        i++;
      }
      blocks.push({ kind: "table", head, rows, align });
      continue;
    }
    if (line.trimStart().startsWith(">")) {
      const body: string[] = [];
      while (i < lines.length && (lines[i] ?? "").trimStart().startsWith(">")) {
        body.push((lines[i] ?? "").trimStart().replace(/^>\s?/, ""));
        i++;
      }
      blocks.push({ kind: "quote", text: body.join("\n") });
      continue;
    }
    const bullet = BULLET.exec(line);
    const numbered = NUMBERED.exec(line);
    if (bullet || numbered) {
      const ordered = !bullet;
      const items: string[] = [];
      const start = numbered ? Number(numbered[1]) : 1;
      while (i < lines.length) {
        const current = lines[i] ?? "";
        const m = ordered ? NUMBERED.exec(current) : BULLET.exec(current);
        if (m) {
          items.push((ordered ? m[2] : m[1]) ?? "");
        } else if (current.trim() && /^\s{2,}/.test(current) && items.length) {
          items[items.length - 1] += "\n" + current.trim();
        } else {
          break;
        }
        i++;
      }
      blocks.push({ kind: "list", ordered, start, items });
      continue;
    }
    const para: string[] = [];
    while (
      i < lines.length &&
      (lines[i] ?? "").trim() &&
      !FENCE.test(lines[i] ?? "") &&
      !HEADING.test(lines[i] ?? "") &&
      !BULLET.test(lines[i] ?? "") &&
      !NUMBERED.test(lines[i] ?? "") &&
      !(lines[i] ?? "").trimStart().startsWith(">")
    ) {
      para.push(lines[i] ?? "");
      i++;
    }
    blocks.push({ kind: "paragraph", text: para.join("\n") });
  }
  return blocks;
}

const INLINE =
  /(`+)([\s\S]*?[^`])\1(?!`)|\*\*([\s\S]+?)\*\*|__([\s\S]+?)__|~~([\s\S]+?)~~|\*([^*\s][^*]*?)\*|(?<![\w])_([^_\s][^_]*?)_(?![\w])|\[([^\]]+)\]\(([^)\s]+)\)|(https?:\/\/[^\s<>()]+[^\s<>().,;:!?'"])/g;

export function safeHref(url: string): string | null {
  try {
    const parsed = new URL(url);
    return ["http:", "https:", "mailto:"].includes(parsed.protocol)
      ? parsed.href
      : null;
  } catch {
    return null;
  }
}

function inline(text: string, key = "i"): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let n = 0;
  for (const m of text.matchAll(INLINE)) {
    const at = m.index;
    if (at > last)
      out.push(...lines(text.slice(last, at), `${key}t${String(n)}`));
    const k = `${key}-${String(n++)}`;
    if (m[2] !== undefined) {
      out.push(
        <code
          key={k}
          className="rounded bg-sunken px-1 py-0.5 font-mono text-em-sm"
        >
          {m[2].trim()}
        </code>,
      );
    } else if (m[3] !== undefined || m[4] !== undefined) {
      out.push(
        <strong key={k} className="font-semibold">
          {inline(m[3] ?? m[4] ?? "", k)}
        </strong>,
      );
    } else if (m[5] !== undefined) {
      out.push(<del key={k}>{inline(m[5], k)}</del>);
    } else if (m[6] !== undefined || m[7] !== undefined) {
      out.push(<em key={k}>{inline(m[6] ?? m[7] ?? "", k)}</em>);
    } else {
      const label = m[8] ?? m[10] ?? "";
      const href = safeHref(m[9] ?? m[10] ?? "");
      out.push(
        href ? (
          // A known outside object (a PR, an issue, a ticket) shows as its chip.
          <MarkdownLink key={k} href={href}>
            {m[8] !== undefined ? inline(label, k) : label}
          </MarkdownLink>
        ) : (
          <span key={k}>{m[0]}</span>
        ),
      );
    }
    last = at + m[0].length;
  }
  if (last < text.length) out.push(...lines(text.slice(last), `${key}e`));
  return out;
}

/** Keeps single line breaks inside a paragraph. */
function lines(text: string, key: string): ReactNode[] {
  return text.split("\n").map((part, i) => (
    <Fragment key={`${key}${String(i)}`}>
      {i > 0 && <br />}
      {part}
    </Fragment>
  ));
}

function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="overflow-hidden rounded-xl border border-line bg-sunken">
      <div className="flex items-center justify-between border-b border-line px-3 py-1 text-xs text-ink-3">
        <span className="font-mono">{lang || "text"}</span>
        <button
          type="button"
          className="rounded px-1.5 py-0.5 hover:bg-panel hover:text-ink"
          onClick={() => {
            void navigator.clipboard.writeText(code).then(() => {
              setCopied(true);
              setTimeout(() => {
                setCopied(false);
              }, 1500);
            });
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto px-3 py-2.5 font-mono text-body-sm leading-relaxed">
        <code>{code}</code>
      </pre>
    </div>
  );
}

const headingSize = ["", "text-lg", "text-base", "text-body"];

export function Markdown({
  text,
  className,
}: {
  text: string;
  className?: string;
}) {
  const blocks = parseBlocks(text);
  return (
    <div className={cn("flex flex-col gap-2.5 break-words", className)}>
      {blocks.map((b, i) => {
        const k = String(i);
        switch (b.kind) {
          case "heading":
            return (
              <p
                key={k}
                role="heading"
                aria-level={b.level}
                className={cn(
                  "font-display font-semibold",
                  headingSize[Math.min(b.level, 3)],
                )}
              >
                {inline(b.text, k)}
              </p>
            );
          case "paragraph":
            return <p key={k}>{inline(b.text, k)}</p>;
          case "code":
            return <CodeBlock key={k} lang={b.lang} code={b.code} />;
          case "rule":
            return <hr key={k} className="border-line" />;
          case "quote":
            return (
              <blockquote
                key={k}
                className="border-l-2 border-line-strong pl-3 text-ink-2"
              >
                {inline(b.text, k)}
              </blockquote>
            );
          case "list": {
            const items = b.items.map((item, j) => (
              <li key={j} className="pl-1">
                {inline(item, `${k}-${String(j)}`)}
              </li>
            ));
            return b.ordered ? (
              <ol key={k} start={b.start} className="list-decimal pl-5">
                {items}
              </ol>
            ) : (
              <ul key={k} className="list-disc pl-5 marker:text-ink-3">
                {items}
              </ul>
            );
          }
          case "table":
            return (
              <div
                key={k}
                className="overflow-x-auto rounded-xl border border-line"
              >
                <table className="w-full text-left text-sm [&_td]:min-w-20 [&_th]:min-w-20">
                  <thead className="bg-sunken text-ink-2">
                    <tr>
                      {b.head.map((h, j) => (
                        <th
                          key={j}
                          className="px-3 py-1.5 font-medium"
                          style={{ textAlign: b.align[j] ?? undefined }}
                        >
                          {inline(h, `${k}h${String(j)}`)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((row, r) => (
                      <tr key={r} className="border-t border-line">
                        {row.map((cell, j) => (
                          <td
                            key={j}
                            className="px-3 py-1.5"
                            style={{ textAlign: b.align[j] ?? undefined }}
                          >
                            {inline(cell, `${k}r${String(r)}c${String(j)}`)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
        }
      })}
    </div>
  );
}
