// Browser port of core/audit/chain.py verify_chain(): the same checks, in the same order, with the same messages.
// Hashing is SHA-256 over canonical JSON (sorted keys, no spaces, UTF-8), exactly as record_hash() in Python.
// tests/chain.test.mjs runs this file under Node against the chains the real Python code wrote at build time.

export const GENESIS_HASH = "0".repeat(64);
const V1 = ["seq", "ts", "agent", "client", "lever", "params", "mode", "result", "approver", "prev_hash", "hash"];
const V2 = V1.concat(["v", "event", "actor_kind", "lever_version", "request_id"]);
const MODES = ["dry-run", "execute", "approve", "reject", "pause", "resume", "invalid"];
const EVENTS = ["lever.invoke", "lever.pause", "proposal.add", "proposal.decide", "model.complete", "job.run"];
const KINDS = ["agent", "human", "unknown"];

function pyRepr(v) {
  if (typeof v === "string") return "'" + v.replace(/\\/g, "\\\\").replace(/'/g, "\\'") + "'";
  if (v === null) return "None";
  if (v === true) return "True";
  if (v === false) return "False";
  return String(v);
}

// json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
export function canonical(value) {
  if (value === null || typeof value !== "object") {
    if (typeof value === "number" && !Number.isInteger(value)) {
      throw new Error("non-integer numbers are not expected in audit records");
    }
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  const keys = Object.keys(value).sort();
  return "{" + keys.map((k) => JSON.stringify(k) + ":" + canonical(value[k])).join(",") + "}";
}

export async function sha256Hex(text) {
  const bytes = new TextEncoder().encode(text);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

export async function recordHash(record) {
  const body = {};
  for (const k of Object.keys(record)) if (k !== "hash") body[k] = record[k];
  return sha256Hex(canonical(body));
}

function sameKeys(record, expected) {
  const keys = Object.keys(record);
  return keys.length === expected.length && expected.every((k) => Object.prototype.hasOwnProperty.call(record, k));
}

function positiveInt(v) {
  return typeof v === "number" && Number.isInteger(v) && v >= 1;
}

function shapeProblem(record, seenV2) {
  if (!("v" in record)) {
    if (seenV2) return "v1 record after a v2 record (versions only move forward)";
    if (!sameKeys(record, V1)) return "record fields are missing or unexpected";
    return null;
  }
  const version = record.v;
  if (typeof version === "boolean" || version !== 2) return "unknown record version " + pyRepr(version);
  if (!sameKeys(record, V2)) return "record fields are missing or unexpected";
  for (const [field, allowed] of [["mode", MODES], ["event", EVENTS], ["actor_kind", KINDS]]) {
    if (!allowed.includes(record[field])) return field + " " + pyRepr(record[field]) + " is not a known value";
  }
  if (record.lever_version !== null && !positiveInt(record.lever_version)) {
    return "lever_version must be a positive integer or null";
  }
  if (typeof record.request_id !== "string" || !record.request_id) return "request_id must be a non-empty string";
  return null;
}

// lines: the raw JSONL lines as written; head: {seq, hash} or null (no head pin checked).
export async function verifyLines(lines, head) {
  let prev = GENESIS_HASH;
  let v1 = 0;
  let v2 = 0;
  const done = (ok, brokenSeq, reason) => {
    const records = v1 + v2;
    const line = ok ? `OK: ${records} records, ${reason}` : `BROKEN at seq ${brokenSeq}: ${reason}`;
    return { ok, records, broken_seq: brokenSeq, reason, line, v1, v2 };
  };
  for (let i = 0; i < lines.length; i++) {
    const expected = i + 1;
    const raw = lines[i];
    if (!raw.trim()) return done(false, expected, `blank line where seq ${expected} should be`);
    let record;
    try { record = JSON.parse(raw); } catch (e) { return done(false, expected, "record is not valid JSON"); }
    if (record === null || typeof record !== "object" || Array.isArray(record)) {
      return done(false, expected, "record fields are missing or unexpected");
    }
    const problem = shapeProblem(record, v2 > 0);
    if (problem) return done(false, expected, problem);
    if (record.seq !== expected) return done(false, expected, `seq is ${pyRepr(record.seq)}, expected ${expected}`);
    if (record.prev_hash !== prev) return done(false, expected, "prev_hash does not match the previous record");
    let computed;
    try { computed = await recordHash(record); } catch (e) { return done(false, expected, "record cannot be hashed here: " + e.message); }
    if (computed !== record.hash) return done(false, expected, "hash does not match the record content");
    if (raw !== canonical(record)) return done(false, expected, "record bytes are not in canonical form (edited)");
    prev = record.hash;
    if ("v" in record) v2++; else v1++;
  }
  const count = v1 + v2;
  if (head === null || head === undefined) return done(true, null, "chain intact (no head pin checked)");
  if (head.seq > count) return done(false, count + 1, `log ends at seq ${count} but the head pins seq ${head.seq}`);
  if (head.seq < count) return done(false, head.seq + 1, `records after the pinned head seq ${head.seq}`);
  if (head.hash !== prev) return done(false, count || null, "last record hash does not match the head pin");
  return done(true, null, "chain intact and matches the head pin");
}
