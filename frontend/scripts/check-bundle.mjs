// Bundle budgets (PIVOT §23): gzip sizes of the built JavaScript, checked after `vite build`.
// The entry chunk is what every visitor downloads before the first paint; route chunks load on
// navigation. Measured 2026-10-20: entry 122 KB, largest route chunk (Cytoscape graph) 142 KB.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const ENTRY_BUDGET_KB = 135;
const CHUNK_BUDGET_KB = 150;
// The landing page's 3D stage (three.js + bloom) is an enhancement, not a route: it is requested
// only on wide screens with WebGL, after the page has painted, and never on phones (which get
// the 2D seal). It gets its own explicit budget rather than loosening every route's.
const ENHANCEMENT_BUDGET_KB = 260;
const ENHANCEMENTS = /^VaultScene-/;
const assets = join(import.meta.dirname, "..", "dist", "assets");
const html = readFileSync(join(import.meta.dirname, "..", "dist", "index.html"), "utf8");
const entry = /src="\/assets\/([^"]+\.js)"/.exec(html)?.[1];
if (!entry) throw new Error("no entry script in dist/index.html — run `vite build` first");

let failed = false;
for (const file of readdirSync(assets).filter((f) => f.endsWith(".js"))) {
  const kb = gzipSync(readFileSync(join(assets, file))).length / 1024;
  const budget =
    file === entry
      ? ENTRY_BUDGET_KB
      : ENHANCEMENTS.test(file)
        ? ENHANCEMENT_BUDGET_KB
        : CHUNK_BUDGET_KB;
  if (kb > budget || file === entry || ENHANCEMENTS.test(file)) {
    const verdict = kb > budget ? "OVER" : "ok  ";
    console.log(`${verdict} ${file}: ${kb.toFixed(1)} KB gzip (budget ${String(budget)} KB)`);
  }
  failed ||= kb > budget;
}
if (failed) process.exit(1);
console.log("bundle budgets met");
