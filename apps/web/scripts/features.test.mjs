// Unit tests for the rules behind six screens (Vision, Chats, Inbox, Team, Setup,
// Settings): the pure functions their components draw from, and the read-only Inbox
// notes rendered to HTML. Run with the TSX loader (`pnpm test`).
import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const vision = await import("../src/features/vision/format.ts");
const goalText = await import("../src/features/vision/goal-text.ts");
const goalModel = await import("../src/features/vision/goal-model.ts");
const { timeline } = await import("../src/features/chats/conversation-poll.ts");
const { FileChip } = await import("../src/features/chats/file-chip.tsx");
const { modelLine } = await import("../src/features/inbox/hire-model.tsx");
const notes = await import("../src/features/inbox/skill-notes.tsx");
const hierarchy = await import("../src/features/workers/hierarchy-layout.ts");
const { founderInitial } =
  await import("../src/features/workers/founder-box.tsx");
const schedule = await import("../src/features/setup/schedule.ts");
const hermes =
  await import("../src/features/settings/hermes-settings-shared.ts");
const sections = await import("../src/features/settings/sections.ts");

describe("vision", () => {
  test("numbers, percents and dates read as the page shows them", () => {
    assert.equal(vision.shown(10000.456), "10,000.46");
    assert.equal(vision.shown(null), "?");
    assert.equal(vision.percent(0.416), 42);
    assert.equal(vision.percent(undefined), null);
    assert.equal(vision.day("2026-12-31"), "Dec 31, 2026");
    assert.equal(vision.weekday("2026-10-27"), "Tuesday, Oct 27");
    assert.equal(vision.shortDay("2026-11-01"), "Nov 1");
    assert.equal(vision.day("soon"), "soon");
    assert.equal(vision.day("2026-13-45"), "2026-13-45");
  });

  test("initials take the capitalised words, else the first two letters", () => {
    assert.equal(vision.initials("Script Writer"), "SW");
    assert.equal(vision.initials("Head of Content"), "HC");
    assert.equal(vision.initials("editor"), "ED");
    assert.equal(vision.initials("social_media-lead"), "SL");
    assert.equal(vision.initials("  "), "?");
  });

  test("planIndex finds every goal and project with its goal", () => {
    const project = { id: 3, children: [{ id: 4 }] };
    const goal = { id: 1, children: [project] };
    const index = vision.planIndex([goal, { id: 2 }]);
    assert.deepEqual([...index.keys()].sort(), [1, 2, 3, 4]);
    assert.equal(index.get(4).goal, goal);
    assert.equal(index.get(3).node, project);
    assert.equal(index.get(2).goal.id, 2);
  });

  test("goal values: numbers, owners, units, project dates, counts", () => {
    assert.equal(goalText.num(3), "3");
    assert.equal(goalText.num(2.5), "2.5");
    assert.equal(goalText.num(1 / 3), "0.33");
    assert.equal(goalText.num(undefined), "?");
    assert.equal(goalText.parseNum(" "), null);
    assert.equal(goalText.parseNum("12"), 12);
    assert.ok(Number.isNaN(goalText.parseNum("twelve")));
    const members = [{ name: "sw", title: "Script Writer" }];
    assert.equal(goalText.ownerName("sw", members), "Script Writer");
    assert.equal(goalText.ownerName("ed", members), "@ed");
    assert.equal(goalText.ownerName("", members), "");
    assert.equal(
      goalText.unitFor({ unit: "followers", title: "Instagram followers" }),
      "",
    );
    assert.equal(goalText.unitFor({ unit: "€", title: "Revenue" }), " €");
    assert.equal(
      goalText.projectShape({ projectKind: "recurring", rhythm: "" }),
      "Recurring",
    );
    assert.equal(
      goalText.projectShape({ startsOn: "2026-11-01", endsOn: "2026-11-15" }),
      "Nov 1 – 15",
    );
    assert.equal(
      goalText.projectShape({ startsOn: "2026-11-01", endsOn: "2026-12-15" }),
      "Nov 1 – Dec 15",
    );
    assert.equal(goalText.projectShape({ endsOn: "2026-12-15" }), "? – Dec 15");
    assert.equal(goalText.projectShape({}), "");
    assert.equal(
      goalModel.cardsOf({ cards: { done: 2, open: 3, blocked: 1 } }),
      6,
    );
    assert.equal(goalModel.started({ progress: 0 }), false);
    assert.equal(goalModel.started({ progress: 0.1 }), true);
  });
});

describe("chats", () => {
  test("each reply keeps its turn; a stopped turn sits after what it answered", () => {
    const messages = [
      { id: 1, from: "owner" },
      { id: 2, from: "agent" },
      { id: 3, from: "owner" },
    ];
    const turns = [
      { id: 10, replyId: 2, status: "done" },
      { id: 11, replyId: null, status: "stopped", askedUpTo: 3 },
      { id: 12, replyId: null, status: "running", askedUpTo: 3 },
    ];
    const items = timeline(messages, turns);
    assert.deepEqual(
      items.map((i) => (i.kind === "owner" ? `o${i.message.id}` : i.key)),
      ["o1", "r2", "o3", "n11"],
    );
    assert.equal(items[1].turn.id, 10);
    assert.equal(items[3].reply, null);
  });

  test("a file chip links when the file can be fetched, with its size in words", () => {
    const link = renderToStaticMarkup(
      createElement(FileChip, { href: "/f/1", name: "a.pdf", size: 2560 }),
    );
    assert.match(link, /^<a href="\/f\/1"/);
    assert.match(link, />3 KB</);
    const plain = renderToStaticMarkup(
      createElement(FileChip, { href: null, name: "b", size: 3 * 1024 * 1024 }),
    );
    assert.match(plain, /^<div /);
    assert.match(plain, />3\.0 MB</);
    assert.match(
      renderToStaticMarkup(
        createElement(FileChip, { href: null, name: "c", size: 12 }),
      ),
      />12 B</,
    );
  });
});

describe("inbox", () => {
  const choices = {
    models: [{ id: "claude-haiku-4-5", label: "Claude Haiku 4.5" }],
  };

  test("a hire's model in one line", () => {
    assert.equal(
      modelLine({ model: "claude-haiku-4-5", effort: "low" }, choices),
      "Claude Haiku 4.5 · low",
    );
    assert.equal(
      modelLine({ model: "x", effort: "none" }, null),
      "x · no reasoning",
    );
    assert.equal(modelLine({ model: "x", effort: "standard" }, null), "x");
    assert.equal(modelLine(null, choices), "");
  });

  test("the skill notes draw what the core sent, nothing for a broken detail", () => {
    const improved = JSON.stringify({
      batch: "b",
      items: [
        {
          candidate: 1,
          itemId: 7,
          name: "seo",
          status: "promoted",
          from: 2,
          to: 3,
          why: "w",
          note: "n",
        },
        {
          candidate: 2,
          itemId: 8,
          name: "copy",
          status: "discarded",
          from: 1,
          to: null,
          why: "w",
          note: "n",
        },
      ],
    });
    const html = renderToStaticMarkup(
      createElement(notes.SkillsImprovedNote, {
        workspaceId: "a b",
        detail: improved,
      }),
    );
    assert.match(html, /v2 → v3/);
    assert.match(html, /kept v1/);
    assert.match(html, /href="\/w\/a%20b\/settings\/capabilities\/skills\/7"/);
    assert.equal((html.match(/<a /g) ?? []).length, 1);
    assert.equal(
      renderToStaticMarkup(
        createElement(notes.SkillsImprovedNote, {
          workspaceId: "a",
          detail: "{",
        }),
      ),
      "",
    );
    const request = renderToStaticMarkup(
      createElement(notes.SkillRequestNote, {
        workspaceId: "a",
        detail: JSON.stringify({
          request: 1,
          status: "landed",
          source: "github",
          note: "Done",
        }),
      }),
    );
    assert.match(request, /From github/);
    assert.match(request, /href="\/w\/a\/settings\/skill-growth"/);
  });
});

describe("workers", () => {
  const box = (name, children = []) => ({
    worker: { name },
    pending: null,
    children,
  });

  test("the layout centres parents over their children", () => {
    const root = box("cofounder", [box("a"), box("b")]);
    const laid = hierarchy.layout(root);
    const w = hierarchy.BOX_W * 2 + 28;
    assert.equal(laid.width, w);
    assert.equal(laid.height, hierarchy.BOX_H * 2 + hierarchy.GAP_Y);
    assert.equal(laid.placed[0].x, (w - hierarchy.BOX_W) / 2);
    assert.deepEqual(
      laid.placed.slice(1).map((p) => [p.x, p.y]),
      [
        [0, hierarchy.BOX_H + hierarchy.GAP_Y],
        [hierarchy.BOX_W + 28, hierarchy.BOX_H + hierarchy.GAP_Y],
      ],
    );
  });

  test("the Founder sits left of the Co-Founder, the chart moves right for him", () => {
    const laid = hierarchy.layout(box("cofounder"));
    assert.equal(hierarchy.besideFounder(laid, false).founderAt, null);
    const beside = hierarchy.besideFounder(laid, true);
    assert.deepEqual(beside.founderAt, { x: 0, y: 0 });
    assert.equal(beside.placed[0].x, hierarchy.BOX_W + 56);
    assert.equal(beside.width, laid.width + hierarchy.BOX_W + 56);
  });

  test("keys and initials", () => {
    assert.equal(hierarchy.keyOf(box("ed")), "ed");
    assert.equal(hierarchy.keyOf(box(undefined)), "cofounder");
    assert.equal(
      hierarchy.keyOf({ ...box("x"), pending: { id: 9 } }),
      "pending-9",
    );
    assert.equal(founderInitial({ name: "hana", title: "CEO" }), "H");
    assert.equal(founderInitial({ name: "", title: " ceo" }), "C");
    assert.equal(founderInitial({ name: "", title: "" }), "F");
  });
});

describe("setup", () => {
  const forms = [
    [{ kind: "daily", time: "08:05" }, "5 8 * * *", "Every day at 08:05"],
    [{ kind: "weekdays", time: "09:00" }, "0 9 * * 1-5", "Weekdays at 09:00"],
    [
      { kind: "weekly", time: "09:00", day: 1 },
      "0 9 * * 1",
      "Mondays at 09:00",
    ],
    [
      { kind: "monthly", time: "07:30", date: 3 },
      "30 7 3 * *",
      "Day 3 of every month at 07:30",
    ],
    [{ kind: "hours", every: 1, minute: 5 }, "5 * * * *", "Every hour at :05"],
    [
      { kind: "hours", every: 6, minute: 0 },
      "0 */6 * * *",
      "Every 6 hours at :00",
    ],
  ];
  for (const [form, cron, words] of forms) {
    test(`${form.kind} ↔ ${cron}`, () => {
      assert.equal(schedule.toCron(form), cron);
      assert.deepEqual(schedule.fromCron(cron), form);
      assert.equal(schedule.describeCron(cron), words);
    });
  }

  test("anything else stays custom, in Hermes's words when known", () => {
    assert.deepEqual(schedule.fromCron("0 9 1-7 * 1"), {
      kind: "custom",
      cron: "0 9 1-7 * 1",
    });
    assert.deepEqual(schedule.fromCron("0 */5 * * *").kind, "custom");
    assert.equal(
      schedule.toCron({ kind: "custom", cron: " 0 9 * * 0 " }),
      "0 9 * * 0",
    );
    assert.equal(
      schedule.describeCron("0 9 1-7 * 1", "First Monday"),
      "First Monday",
    );
    assert.equal(schedule.describeCron("0 9 1-7 * 1"), "0 9 1-7 * 1");
    assert.equal(schedule.describeCron("every morning"), "every morning");
    assert.equal(schedule.describeCron("  "), "Invalid schedule");
  });
});

describe("settings", () => {
  test("a Hermes value in plain words", () => {
    assert.equal(hermes.shownValue(true), "on");
    assert.equal(hermes.shownValue(false), "off");
    assert.equal(hermes.shownValue(null), "not set");
    assert.equal(hermes.shownValue(""), "empty");
    assert.equal(hermes.shownValue(3), "3");
    assert.equal(hermes.shownValue([]), "none");
    assert.equal(hermes.shownValue({}), "none");
    assert.equal(hermes.shownValue({ a: 1 }), '{"a":1}');
  });

  test("sections have unique slugs and known groups", () => {
    const slugs = sections.settingsSections.map((s) => s.slug);
    assert.equal(new Set(slugs).size, slugs.length);
    for (const s of sections.settingsSections) {
      const group = sections.groupOf(s);
      assert.ok(group === null || typeof group === "string");
    }
  });
});
