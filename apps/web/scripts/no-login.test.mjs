// AGOS has no login: every page and API route is served with no cookie to a
// request from this machine or through the owner's Tailscale, and refused to
// anything else (src/server/access.ts, checked by src/proxy.ts on every request).
// Node strips the types of the .ts files it imports; the hook below resolves the
// two imports Next's bundler resolves for the app (`next/server`, `./server/access`).
import assert from "node:assert/strict";
import {
  mkdtempSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { registerHooks } from "node:module";
import { join, relative, sep } from "node:path";
import { test } from "node:test";

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === "next/server")
      return nextResolve("next/server.js", context);
    const ours = context.parentURL?.includes("/apps/web/src/");
    if (ours && specifier.startsWith("./") && !/\.\w+$/.test(specifier))
      return nextResolve(`${specifier}.ts`, context);
    return nextResolve(specifier, context);
  },
});

// Never this machine's own saved access (~/agos-data): a folder with nothing saved,
// unless a test names its own.
process.env.AGOS_INTERNAL_TOKEN_FILE = join(
  tmpdir(),
  `agos-no-login-${String(process.pid)}`,
  "internal.token",
);

const { NextRequest } = await import("next/server");
const { proxy, config } = await import("../src/proxy.ts");
const { decideAccess } = await import("../src/server/access.ts");

const SRC = join(import.meta.dirname, "..", "src");
const APP = join(SRC, "app");

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

/** Every page and API route of the app, as a URL path (params filled in). */
function routes() {
  return files(APP)
    .filter((f) => /[/\\](page\.tsx|route\.ts)$/.test(f))
    .map(
      (f) =>
        (
          "/" +
          relative(APP, f)
            .split(sep)
            .slice(0, -1)
            .filter((part) => !/^\(.*\)$/.test(part)) // route groups
            .map((part) => part.replace(/^\[\.{0,3}(.+)\]$/, "x-$1"))
            .join("/")
        ).replace(/\/$/, "") || "/",
    );
}

async function ask(path, headers, method = "GET") {
  return proxy(new NextRequest(`http://agos.test${path}`, { method, headers }));
}

async function withEnv(env, run) {
  const before = {};
  for (const key of Object.keys(env)) {
    before[key] = process.env[key];
    process.env[key] = env[key];
  }
  try {
    return await run();
  } finally {
    for (const key of Object.keys(env)) {
      if (before[key] === undefined) delete process.env[key];
      else process.env[key] = before[key];
    }
  }
}

const TAILSCALE = {
  AGOS_ALLOWED_HOSTS: "agos.tail1234.ts.net",
  AGOS_TAILSCALE_USERS: "owner@example.com",
};

test("the app has its pages and no login page left", () => {
  const all = routes();
  assert.ok(all.includes("/") && all.includes("/settings/x-section"), all);
  assert.ok(all.length > 20, `only ${String(all.length)} routes found`);
  for (const gone of ["/login", "/setup", "/invite/x-token", "/m"])
    assert.ok(!all.includes(gone), `${gone} is still a route`);
  for (const file of files(SRC).filter((f) => /\.tsx?$/.test(f))) {
    const text = readFileSync(file, "utf8");
    assert.doesNotMatch(text, /agos_session|server\/session|\/auth\//, file);
  }
});

test("every page and API route opens on this machine with no cookie", async () => {
  for (const host of ["localhost:3000", "127.0.0.1:3000", "[::1]:3000"]) {
    for (const path of routes()) {
      const response = await ask(path, { host });
      assert.equal(response.status, 200, `${host} ${path}`);
      assert.equal(response.headers.get("location"), null, path);
      assert.equal(response.headers.get("x-middleware-next"), "1", path);
    }
  }
  // Server actions (POST) too.
  const posted = await ask("/settings/general", { host: "localhost" }, "POST");
  assert.equal(posted.headers.get("x-middleware-next"), "1");
});

test("through the owner's Tailscale it opens with no cookie", async () => {
  await withEnv(TAILSCALE, async () => {
    for (const path of routes()) {
      const response = await ask(path, {
        host: "agos.tail1234.ts.net",
        "tailscale-user-login": "Owner@Example.com",
      });
      assert.equal(response.headers.get("x-middleware-next"), "1", path);
    }
  });
});

test("any other request is refused", async () => {
  await withEnv(TAILSCALE, async () => {
    const refused = [
      { host: "evil.example" }, // DNS rebinding: another site's name
      { host: "evil.example", "tailscale-user-login": "owner@example.com" },
      { host: "192.168.1.20:3000" }, // the LAN address
      { host: "agos.tail1234.ts.net" }, // Tailscale, but not a Tailscale login
      { host: "agos.tail1234.ts.net", "tailscale-user-login": "guest@x.com" },
      { host: "localhost.evil.example" },
      {}, // no Host at all
    ];
    for (const headers of refused) {
      for (const path of ["/", "/settings/access", "/api/health"]) {
        const response = await ask(path, headers);
        assert.equal(response.status, 403, JSON.stringify(headers) + path);
        assert.equal(response.headers.get("x-middleware-next"), null);
      }
    }
  });
  // With no Tailscale set up, only this machine.
  await withEnv({ AGOS_ALLOWED_HOSTS: "", AGOS_TAILSCALE_USERS: "" }, () => {
    assert.equal(decideAccess("localhost:3000", null), "allow");
    assert.equal(
      decideAccess("agos.tail1234.ts.net", "owner@example.com"),
      "refuse",
    );
  });
});

test("a change sent from another site is refused and told to the core", async () => {
  const folder = mkdtempSync(join(tmpdir(), "agos-security-"));
  mkdirSync(join(folder, "system"));
  writeFileSync(join(folder, "system", "internal.token"), "tok-123");
  const told = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    told.push({ url: String(url), init });
    return new Response(null, { status: 204 });
  };
  try {
    await withEnv(
      {
        AGOS_INTERNAL_TOKEN_FILE: join(folder, "system", "internal.token"),
        AGOS_CORE_URL: "http://127.0.0.1:9",
      },
      async () => {
        const host = "localhost:3000";
        const from = (origin) =>
          ask("/settings/general?x=secret", { host, origin }, "POST");
        assert.equal((await from("https://evil.example")).status, 403);
        assert.equal((await from("null")).status, 403);
        // Same site, a read, or no Origin (not a browser): as before.
        const same = await from("http://localhost:3000");
        assert.equal(same.headers.get("x-middleware-next"), "1");
        const read = await ask("/", { host, origin: "https://evil.example" });
        assert.equal(read.headers.get("x-middleware-next"), "1");
        const bare = await ask("/settings/general", { host }, "POST");
        assert.equal(bare.headers.get("x-middleware-next"), "1");
        // A refused Host is told too.
        assert.equal((await ask("/", { host: "evil.example" })).status, 403);
      },
    );
    const bodies = told.map((t) => JSON.parse(t.init.body));
    assert.deepEqual(
      bodies.map((b) => b.kind),
      ["origin", "origin", "host"],
    );
    assert.equal(bodies[0].where, "/settings/general"); // no query string
    assert.equal(bodies[0].detail, "https://evil.example");
    assert.equal(told[0].url, "http://127.0.0.1:9/security/events");
    assert.equal(told[0].init.headers["x-agos-internal"], "tok-123");
  } finally {
    globalThis.fetch = realFetch;
    rmSync(folder, { recursive: true, force: true });
  }
});

test("the proxy runs for every dynamic path, the image optimizer included", async () => {
  // Next reads each matcher as a whole-path pattern.
  const runs = (path) =>
    config.matcher.some((m) => new RegExp(`^${m}$`).test(path));
  for (const path of ["/", "/settings", "/api/health", "/_next/image"])
    assert.ok(runs(path), path);
  assert.equal(runs("/_next/static/chunks/app.js"), false);
  // And a DNS-rebinding page asking the optimizer is refused like any page.
  const response = await ask("/_next/image?url=%2Ffavicon.ico&w=64&q=75", {
    host: "evil.example",
  });
  assert.equal(response.status, 403);
});

/** A data folder where Settings → Access saved `saved` (or nothing: null). */
function savedAccess(saved) {
  const folder = mkdtempSync(join(tmpdir(), "agos-access-"));
  mkdirSync(join(folder, "system"));
  if (saved)
    writeFileSync(
      join(folder, "system", "remote-access.json"),
      JSON.stringify(saved),
    );
  return {
    folder,
    env: {
      AGOS_INTERNAL_TOKEN_FILE: join(folder, "system", "internal.token"),
      AGOS_ALLOWED_HOSTS: "",
      AGOS_TAILSCALE_USERS: "",
    },
  };
}

test("the address and login Settings → Access saved are let in, nothing else", async () => {
  const { folder, env } = savedAccess({
    host: "agos-box.tail1234.ts.net",
    user: "owner@example.com",
    alsoAllow: ["sis@gmail.com"],
    port: 3000,
  });
  try {
    await withEnv(env, async () => {
      const host = "agos-box.tail1234.ts.net";
      for (const user of ["owner@example.com", "Sis@Gmail.com"]) {
        const response = await ask("/settings/access", {
          host,
          "tailscale-user-login": user,
        });
        assert.equal(response.headers.get("x-middleware-next"), "1", user);
      }
      for (const headers of [
        { host }, // no Tailscale login
        { host, "tailscale-user-login": "guest@x.com" },
        {
          host: "other.tail1234.ts.net",
          "tailscale-user-login": "owner@example.com",
        },
        { host: "evil.example", "tailscale-user-login": "owner@example.com" },
      ]) {
        const response = await ask("/", headers);
        assert.equal(response.status, 403, JSON.stringify(headers));
      }
      assert.equal(decideAccess("localhost:3000", null), "allow");
    });
    // The environment's lists still work beside the saved ones (merged).
    await withEnv({ ...env, ...TAILSCALE }, () => {
      assert.equal(
        decideAccess("agos.tail1234.ts.net", "owner@example.com"),
        "allow",
      );
      assert.equal(
        decideAccess("agos-box.tail1234.ts.net", "sis@gmail.com"),
        "allow",
      );
    });
  } finally {
    rmSync(folder, { recursive: true, force: true });
  }
});

test("with nothing saved (turned off), Tailscale requests are refused", async () => {
  const { folder, env } = savedAccess(null);
  try {
    await withEnv(env, () => {
      assert.equal(
        decideAccess("agos-box.tail1234.ts.net", "owner@example.com"),
        "refuse",
      );
      assert.equal(decideAccess("127.0.0.1:3000", null), "allow");
    });
  } finally {
    rmSync(folder, { recursive: true, force: true });
  }
});
