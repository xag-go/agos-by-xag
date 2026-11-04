// The old minimatch API (a callable default export with the helpers hung on it), backed
// by minimatch 11: GHSA-g3hv-75wg-m249 (minimatch < 11.0.1) has no fix in the 3.x/5.x
// lines that eslint 9, its plugins and @redocly still require.
"use strict";
const m = require("minimatch");

function minimatch(path, pattern, options) {
  return m.minimatch(path, pattern, options);
}
Object.assign(minimatch, m);
minimatch.minimatch = minimatch;
minimatch.default = minimatch;
module.exports = minimatch;
