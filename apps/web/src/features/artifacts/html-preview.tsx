"use client";

/**
 * An HTML artifact, shown walled off (Paperclip's approach, HtmlArtifactPreview):
 * the document goes in as `srcdoc` in an iframe sandboxed with `allow-scripts`
 * only — never `allow-same-origin`, so its scripts have no AGOS cookies, storage
 * or origin — and a Content-Security-Policy is put at its head so nothing in it
 * can call out (connect-src 'none'), frame anything (frame-src 'none'), move its
 * base (base-uri 'none') or post a form (form-action 'none'). No referrer leaves.
 */
export function HtmlPreview({ html, title }: { html: string; title: string }) {
  return (
    <iframe
      title={title}
      sandbox="allow-scripts"
      referrerPolicy="no-referrer"
      srcDoc={withPolicy(html)}
      className="h-[70dvh] w-full rounded-xl border border-line bg-white"
    />
  );
}

const CSP =
  "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; " +
  "img-src data: blob:; media-src data: blob:; font-src data:; " +
  "connect-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'";

const META = `<meta http-equiv="Content-Security-Policy" content="${CSP}">`;

/** The policy as the first thing the document's head reads. */
function withPolicy(html: string): string {
  const head = /<head[^>]*>/i.exec(html);
  if (head) {
    const at = head.index + head[0].length;
    return html.slice(0, at) + META + html.slice(at);
  }
  const open = /<html[^>]*>/i.exec(html);
  if (open) {
    const at = open.index + open[0].length;
    return `${html.slice(0, at)}<head>${META}</head>${html.slice(at)}`;
  }
  return `<!doctype html><html><head>${META}</head><body>${html}</body></html>`;
}
