/** Read-only visual regression check. Install playwright-core separately and set
 * PLAYWRIGHT_MODULE to its entry point, or install it in this workspace.
 * UI_BASE_URL defaults to the isolated preview; never submits product forms.
 */
import assert from "node:assert/strict";
const { chromium } = await import(
  process.env.PLAYWRIGHT_MODULE || "playwright-core"
);
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
  args: ["--no-sandbox"],
});
const base = process.env.UI_BASE_URL || "http://127.0.0.1:3001";
const workspace = process.env.UI_WORKSPACE || "demo";
const routes = [
  "/",
  `/w/${workspace}`,
  `/w/${workspace}/messages`,
  `/w/${workspace}/kanban`,
  "/settings",
  `/w/${workspace}/settings`,
];
let checks = 0;
try {
  for (const width of [390, 768, 1440, 2560]) {
    const context = await browser.newContext({
      viewport: { width, height: 960 },
    });
    await context.route("**/*", (route) =>
      route.request().method() === "GET" ? route.continue() : route.abort(),
    );
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    for (const theme of ["light", "dark"]) {
      await context.addCookies([
        { name: "agos-theme", value: theme, url: base },
      ]);
      for (const path of routes) {
        const response = await page.goto(base + path);
        assert.equal(
          response.status(),
          200,
          `${path} must render successfully`,
        );
        await page.waitForTimeout(300);
        assert.ok(
          await page.locator("main h1").count(),
          `${path} must render app content`,
        );
        const dimensions = await page.evaluate(() => ({
          width: innerWidth,
          scroll: document.documentElement.scrollWidth,
        }));
        assert.ok(
          dimensions.scroll <= dimensions.width,
          `${theme} ${width} ${path}: page overflow ${JSON.stringify(dimensions)}`,
        );
        checks++;
      }
    }
    assert.deepEqual(errors, [], "No client errors");
    await context.close();
  }
  console.log(
    `PASS ${checks} rendered route/theme/viewport combinations; no page overflow or client exceptions.`,
  );
} finally {
  await browser.close();
}
