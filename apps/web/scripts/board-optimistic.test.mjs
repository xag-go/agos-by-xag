// The board's clicks shown at once (W10): the pure part that lays a pending
// click over Hermes's board, and its rollback (the click ends, Hermes's board is
// shown as it is). Node strips the types of the .ts file it imports.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  boardOnScreen,
  boardWithChanges,
  landing,
  withChanges,
} from "../src/features/kanban/optimistic.ts";

const columns = [
  "triage",
  "todo",
  "ready",
  "running",
  "blocked",
  "review",
  "done",
  "archived",
].map((status) => ({ status, label: status, open: true }));

const card = (id, status, extra = {}) => ({
  id,
  title: `Card ${id}`,
  status,
  blockKind: "",
  member: "",
  memberTitle: "",
  goal: false,
  model: "",
  // Derived by the core from Hermes's blocker chain; "" = not waiting.
  attention: "",
  attentionWhy: "",
  holdId: null,
  // The workspace skills the card was made with (their versions pin what the worker read).
  skillPins: [],
  // The goal it serves (its body's '## Goal' line or a parent's) and its title.
  goalId: null,
  goalInherited: false,
  goalTitle: "",
  // Its member's team is stalled by a lead above it ("" = not).
  chainStalled: "",
  // Its review stages / plan first ("Review 2/3 · round 1"); null = no review rules.
  reviewChip: null,
  // Its labels (ids; a block in its Hermes body), Hermes's priority and when it was
  // made: the Board views filter, group and sort on them (Step 58).
  labels: [],
  priority: 0,
  createdAt: 0,
  ...extra,
});

const hermesBoard = () => ({
  columns,
  dispatchSeconds: 60,
  cards: [
    card("t1", "running", { member: "ana", memberTitle: "Ana" }),
    card("t2", "blocked", { blockKind: "needs_input" }),
    card("t3", "done"),
  ],
});

// What the board view shows in each column (kanban-board.tsx filters the same way).
const inColumn = (board, status) =>
  board.cards.filter((c) => c.status === status).map((c) => c.id);

test("a pending click moves the card to its column at once", () => {
  const board = hermesBoard();
  const shown = boardWithChanges(board, [{ card: "t1", status: "done" }]);
  assert.deepEqual(inColumn(shown, "running"), []);
  assert.deepEqual(inColumn(shown, "done"), ["t1", "t3"]);
  // Only the clicked card changes; its other fields stay Hermes's.
  assert.equal(shown.cards[0].memberTitle, "Ana");
  assert.deepEqual(shown.cards[1], board.cards[1]);
});

test("rollback: Hermes's board is never changed, so when the click ends it shows as it was", () => {
  const board = hermesBoard();
  const before = structuredClone(board);
  boardWithChanges(board, [{ card: "t1", status: "archived", blockKind: "" }]);
  assert.deepEqual(board, before);
  // No pending click left (success or failure): exactly Hermes's board.
  assert.equal(boardWithChanges(board, []), board);
  assert.deepEqual(inColumn(boardWithChanges(board, []), "running"), ["t1"]);
});

test("two quick clicks on one card: the last one shows, each field from the newest click", () => {
  const board = hermesBoard();
  const shown = boardWithChanges(board, [
    { card: "t1", status: "blocked", blockKind: "" },
    { card: "t1", member: "", memberTitle: "" },
    { card: "t1", status: "done" },
  ]);
  const t1 = shown.cards.find((c) => c.id === "t1");
  assert.equal(t1.status, "done");
  assert.equal(t1.memberTitle, "");
  assert.deepEqual(inColumn(shown, "blocked"), ["t2"]);
});

test("a live refresh during the write: the click stays on top of Hermes's newer board (no flicker back)", () => {
  const changes = [{ card: "t2", status: "ready", blockKind: "" }];
  const newer = hermesBoard();
  newer.cards[0] = card("t1", "review", { memberTitle: "Ana" });
  const shown = boardWithChanges(newer, changes);
  assert.deepEqual(inColumn(shown, "ready"), ["t2"]);
  assert.deepEqual(inColumn(shown, "review"), ["t1"]);
  assert.equal(shown.cards[1].blockKind, "");
});

test("the open card gets the same pending fields as its board card", () => {
  const detail = {
    ...card("t2", "blocked", { blockKind: "needs_input" }),
    parents: [],
  };
  const changes = [
    { card: "t2", status: "ready", blockKind: "" },
    { card: "t9", status: "done" },
  ];
  const shown = withChanges(detail, changes);
  assert.equal(shown.status, "ready");
  assert.equal(shown.blockKind, "");
  assert.deepEqual(shown.parents, []);
  assert.equal(detail.status, "blocked");
  assert.equal(withChanges(detail, []), detail);
});

test("landing: where Hermes puts the card after each button", () => {
  const board = hermesBoard();
  assert.equal(landing("done", {}, board), "done");
  assert.equal(landing("archive", {}, board), "archived");
  assert.equal(landing("block", {}, board), "blocked");
  // Unblock and the owner's answer: ready, or todo while a parent isn't finished.
  assert.equal(landing("unblock", { parents: [] }, board), "ready");
  assert.equal(landing("unblock", {}, board), "ready");
  assert.equal(landing("unblock", { parents: ["t3"] }, board), "ready");
  assert.equal(landing("unblock", { parents: ["t1", "t3"] }, board), "todo");
  const archivedParent = hermesBoard();
  archivedParent.cards[0] = card("t1", "archived");
  assert.equal(
    landing("unblock", { parents: ["t1"] }, archivedParent),
    "ready",
  );
});

test("landing: nothing early when the screen can't tell for sure", () => {
  const board = hermesBoard();
  // A parent not on the board: its status is unknown here.
  assert.equal(landing("unblock", { parents: ["gone"] }, board), null);
  // Hermes's workflow without that column: the card would vanish, so no move.
  const noArchive = { ...board, columns: columns.slice(0, -1) };
  assert.equal(landing("archive", {}, noArchive), null);
  assert.equal(landing("done", {}, { ...board, columns: undefined }), null);
});

test("boardOnScreen keeps what the board shows and drops the cards' text", () => {
  const full = {
    columns,
    dispatchSeconds: 30,
    members: [{ name: "ana", title: "Ana" }],
    cards: [
      {
        ...card("t1", "running", { member: "ana", memberTitle: "Ana" }),
        body: "a long description",
        createdAt: 1,
        createdBy: "owner",
        statusLabel: "Running",
        actions: ["done"],
      },
    ],
  };
  const shown = boardOnScreen(full);
  assert.deepEqual(shown, {
    columns,
    dispatchSeconds: 30,
    cards: [
      card("t1", "running", {
        member: "ana",
        memberTitle: "Ana",
        createdAt: 1,
      }),
    ],
  });
});
