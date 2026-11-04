// The Board's views (Step 58): filters, group-by and sort over the board's one
// read, the URL that carries a view, and a saved view with the URL's changes on
// top. Node strips the types of the .ts file it imports.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  goalAt,
  groupCards,
  queryFrom,
  queryString,
  visibleCards,
} from "../src/features/kanban/views.ts";

const card = (id, extra = {}) => ({
  id,
  title: `Card ${id}`,
  status: "ready",
  blockKind: "",
  member: "",
  memberTitle: "",
  goal: false,
  model: "",
  attention: "",
  attentionWhy: "",
  holdId: null,
  skillPins: [],
  goalId: null,
  goalInherited: false,
  goalTitle: "",
  chainStalled: "",
  reviewChip: null,
  labels: [],
  priority: 0,
  createdAt: 0,
  ...extra,
});

const goals = [
  { id: 1, parentId: null, level: "vision", title: "Vision" },
  { id: 2, parentId: 1, level: "goal", title: "Grow" },
  { id: 3, parentId: 2, level: "project", title: "Launch blog" },
];

const cards = [
  card("t_1", {
    member: "ana",
    memberTitle: "Ana",
    labels: [7],
    goalId: 3,
    createdAt: 3,
  }),
  card("t_2", {
    status: "blocked",
    blockKind: "needs_input",
    labels: [7, 8],
    createdAt: 1,
  }),
  card("t_3", {
    status: "review",
    member: "owner",
    reviewChip: { phase: "review" },
    memberTitle: "",
    createdAt: 2,
    title: "Approve the logo",
  }),
  card("t_4", { memberTitle: "Co-Founder", goalId: 2, createdAt: 4 }),
];

const ids = (list) => list.map((c) => c.id);

test("filters: member, label, goal (and what is under it), review, blocked, text", () => {
  const q = (params) => queryFrom(params, []);
  assert.deepEqual(ids(visibleCards(cards, q({ m: "ana" }), goals)), ["t_1"]);
  assert.deepEqual(ids(visibleCards(cards, q({ m: "cofounder" }), goals)), [
    "t_4",
  ]);
  assert.deepEqual(ids(visibleCards(cards, q({ lb: "8" }), goals)), ["t_2"]);
  // A goal shows the cards of its projects too.
  assert.deepEqual(ids(visibleCards(cards, q({ goal: "2" }), goals)), [
    "t_4",
    "t_1",
  ]);
  assert.deepEqual(ids(visibleCards(cards, q({ rv: "at_owner" }), goals)), [
    "t_3",
  ]);
  assert.deepEqual(ids(visibleCards(cards, q({ bl: "asks" }), goals)), ["t_2"]);
  assert.deepEqual(ids(visibleCards(cards, q({ q: "LOGO" }), goals)), ["t_3"]);
  // Newest first by default; oldest first on asking.
  assert.deepEqual(ids(visibleCards(cards, q({}), goals)), [
    "t_4",
    "t_1",
    "t_3",
    "t_2",
  ]);
  assert.deepEqual(
    ids(visibleCards(cards, q({ sort: "created-asc" }), goals)),
    ["t_2", "t_3", "t_1", "t_4"],
  );
});

test("group-by: label (a card in each of its labels), project, member", () => {
  const ctx = {
    columns: [],
    labels: [
      { id: 7, name: "Urgent" },
      { id: 8, name: "Blog" },
    ],
    goals,
  };
  const byLabel = groupCards(cards, "label", ctx);
  assert.deepEqual(
    byLabel.map((g) => [g.label, ids(g.cards)]),
    [
      ["Urgent", ["t_1", "t_2"]],
      ["Blog", ["t_2"]],
      ["No label", ["t_3", "t_4"]],
    ],
  );
  const byProject = groupCards(cards, "project", ctx);
  assert.deepEqual(
    byProject.map((g) => [g.label, ids(g.cards)]),
    [
      ["Launch blog", ["t_1"]],
      ["No project", ["t_2", "t_3", "t_4"]],
    ],
  );
  assert.equal(goalAt(3, "goal", goals)?.title, "Grow");
  const byMember = groupCards(cards, "member", ctx);
  // His own Review stage is "You"; the unassigned group comes last.
  assert.deepEqual(
    byMember.map((g) => g.label),
    ["Ana", "You", "Co-Founder", "Nobody yet"],
  );
});

test("the Founder (the owner himself) is a card's member like any other", () => {
  // A card assigned to him on Hermes's board: the core gives member "founder"
  // and his name (Settings → General) as the member slot's words.
  const mine = card("t_9", {
    member: "founder",
    memberTitle: "Sara",
    createdAt: 9,
  });
  const all = [...cards, mine];
  const only = visibleCards(all, queryFrom({ m: "founder" }, []), goals);
  assert.deepEqual(ids(only), ["t_9"]);
  // With the Co-Founder in the same filter, both lanes, nobody else's cards.
  assert.deepEqual(
    ids(visibleCards(all, queryFrom({ m: "founder,cofounder" }, []), goals)),
    ["t_9", "t_4"],
  );
  const byMember = groupCards(all, "member", {
    columns: [],
    labels: [],
    goals,
  });
  const his = byMember.find((g) => g.key === "founder");
  assert.equal(his?.label, "Sara");
  assert.deepEqual(ids(his?.cards ?? []), ["t_9"]);
  // His name is searchable like a member's.
  assert.deepEqual(
    ids(visibleCards(all, queryFrom({ q: "sara" }, []), goals)),
    ["t_9"],
  );
});

test("the URL carries the view: a saved one plus only what differs", () => {
  const views = [
    {
      id: 4,
      name: "Blocked",
      filters: { blocked: "yes", members: ["ana"] },
      groupBy: "member",
      layout: "list",
      columns: ["id", "title"],
    },
  ];
  const saved = queryFrom({ view: "4" }, views);
  assert.equal(saved.blocked, "yes");
  assert.equal(saved.groupBy, "member");
  assert.equal(queryString(saved, views), "view=4");
  const changed = { ...saved, text: "logo", groupBy: "label" };
  const url = queryString(changed, views);
  assert.equal(url, "view=4&q=logo&group=label");
  // Read back: the same query.
  const back = queryFrom(Object.fromEntries(new URLSearchParams(url)), views);
  assert.deepEqual(back, changed);
  // Junk in the URL falls back to the defaults.
  const junk = queryFrom({ group: "planet", lb: "x,3", rv: "?" }, []);
  assert.equal(junk.groupBy, "status");
  assert.deepEqual(junk.labels, [3]);
  assert.equal(junk.review, "");
  assert.equal(queryString(queryFrom({}, []), []), "");
});
