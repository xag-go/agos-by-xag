/* eslint-disable react-hooks/rules-of-hooks, react-hooks/immutability -- a test stand-in for React itself, not a component */
// React for web unit tests (scripts/tsx-hooks.mjs maps `react` imported by src/ to this file):
// the real React, plus a scripted useState for rendering a component in a chosen state.
//
//   withState([status, check, false], () => renderToStaticMarkup(<Card />))
//
// While a script runs, each useState call takes the next value of the script, in call order
// (a component's hooks always run in the same order), and its setter does nothing.
import * as React from "react";

export * from "react";
export default React;

let script = null;

export function withState(values, render) {
  const before = script;
  script = { values, next: 0 };
  try {
    return render();
  } finally {
    script = before;
  }
}

export function useState(initial) {
  if (!script) return React.useState(initial);
  if (script.next >= script.values.length) {
    throw new Error(
      `useState #${script.next + 1}: the script has ${script.values.length} values`,
    );
  }
  return [script.values[script.next++], () => {}];
}
