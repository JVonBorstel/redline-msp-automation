// Parity test: the browser verifier (src/assets/js/chain.js) must give the same verdict as the repo's Python
// verify_chain() on every case in the cases file, which test_site.py writes from real chains and real Python verdicts.
//   node chain.test.mjs <chain.js path> <cases.json path>
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [chainPath, casesPath] = process.argv.slice(2);
const dir = mkdtempSync(join(tmpdir(), "chainjs-"));
const copy = join(dir, "chain.mjs");
writeFileSync(copy, readFileSync(chainPath, "utf8"));
const { verifyLines } = await import(pathToFileURL(copy).href);

const cases = JSON.parse(readFileSync(casesPath, "utf8"));
let pass = 0;
const fails = [];
for (const c of cases) {
  const js = await verifyLines(c.lines, c.head);
  const py = c.python;
  if (js.ok === py.ok && js.broken_seq === py.broken_seq && js.reason === py.reason && js.records === py.records) pass++;
  else fails.push({ name: c.name, js: { ok: js.ok, broken_seq: js.broken_seq, reason: js.reason, records: js.records }, py });
}
console.log(JSON.stringify({ cases: cases.length, pass, fails: fails.slice(0, 5), failed: fails.length }));
process.exit(fails.length ? 1 : 0);
