/**
 * In-browser verification of a signed case file — the same checks as `verita-verify`.
 *
 * RFC 8785 canonical JSON is native here: ECMAScript's Number-to-string and the default
 * (UTF-16 code unit) key sort are exactly what the RFC specifies. Leaves and nodes follow
 * RFC 6962 (0x00 / 0x01 prefixes, split at the largest power of two below n), and the
 * signature is Ed25519 via WebCrypto over `verita-case-v1:<case id>:<root>`. Nothing leaves the
 * browser: the file is read locally.
 */

export interface CaseExport {
  format: string;
  case_id: number;
  items: Record<string, unknown>;
  leaves: Record<string, string>;
  merkle_root: string;
  signature: {
    algorithm: string;
    key_id: string;
    value: string;
    message: string;
    signed_at: string;
  };
  public_key_pem?: string | null;
}

export interface FileCheck {
  valid: boolean;
  signatureValid: boolean;
  rootMatches: boolean;
  recomputedRoot: string;
  changedLeaves: string[];
  keyId: string;
}

export function canonicalize(value: unknown): string {
  if (value === null || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("NaN and Infinity are not JSON numbers");
    return JSON.stringify(value); // ECMAScript Number::toString, -0 → "0"
  }
  if (typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(",")}]`;
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const keys = Object.keys(obj).sort(); // UTF-16 code-unit order, as RFC 8785 requires
    return `{${keys.map((k) => `${JSON.stringify(k)}:${canonicalize(obj[k])}`).join(",")}}`;
  }
  throw new Error(`${typeof value} is not a JSON value`);
}

const encoder = new TextEncoder();

function hex(bytes: ArrayBuffer | Uint8Array): string {
  return Array.from(new Uint8Array(bytes), (b) => b.toString(16).padStart(2, "0")).join("");
}

async function sha256(...parts: Uint8Array[]): Promise<Uint8Array> {
  const total = parts.reduce((n, p) => n + p.length, 0);
  const buf = new Uint8Array(total);
  let offset = 0;
  for (const p of parts) {
    buf.set(p, offset);
    offset += p.length;
  }
  return new Uint8Array(await crypto.subtle.digest("SHA-256", buf));
}

export async function leafHash(name: string, value: unknown): Promise<Uint8Array> {
  return sha256(new Uint8Array([0]), encoder.encode(canonicalize({ name, value })));
}

async function root(hashes: Uint8Array[]): Promise<Uint8Array> {
  if (hashes.length === 1 && hashes[0]) return hashes[0];
  let k = 1;
  while (k * 2 < hashes.length) k *= 2;
  const left = await root(hashes.slice(0, k));
  const right = await root(hashes.slice(k));
  return sha256(new Uint8Array([1]), left, right);
}

export async function merkleRoot(items: Record<string, unknown>): Promise<{
  root: string;
  leaves: Record<string, string>;
}> {
  const names = Object.keys(items).sort();
  const hashes = await Promise.all(names.map((n) => leafHash(n, items[n])));
  const leaves = Object.fromEntries(names.map((n, i) => [n, hex(hashes[i] ?? new Uint8Array())]));
  if (hashes.length === 0) return { root: hex(await sha256()), leaves };
  return { root: hex(await root(hashes)), leaves };
}

function pemToDer(pem: string): Uint8Array<ArrayBuffer> {
  const body = pem.replace(/-----(BEGIN|END) PUBLIC KEY-----/g, "").replace(/\s+/g, "");
  return Uint8Array.from(atob(body), (c) => c.charCodeAt(0));
}

export async function verifySignature(
  pem: string,
  caseId: number,
  rootHex: string,
  signatureB64: string,
): Promise<boolean> {
  try {
    const key = await crypto.subtle.importKey("spki", pemToDer(pem), { name: "Ed25519" }, false, [
      "verify",
    ]);
    const sig = Uint8Array.from(atob(signatureB64), (c) => c.charCodeAt(0));
    const message = encoder.encode(`verita-case-v1:${String(caseId)}:${rootHex}`);
    return await crypto.subtle.verify({ name: "Ed25519" }, key, sig, message);
  } catch {
    return false;
  }
}

/** Recompute leaves and root, check the signature, and name every leaf that changed. */
export async function verifyCaseFile(file: CaseExport, publicKeyPem?: string): Promise<FileCheck> {
  const { root: recomputed, leaves } = await merkleRoot(file.items);
  const names = new Set([...Object.keys(file.leaves), ...Object.keys(leaves)]);
  const changedLeaves = [...names].filter((n) => file.leaves[n] !== leaves[n]).sort();
  const pem = publicKeyPem ?? file.public_key_pem ?? "";
  const signatureValid = pem
    ? await verifySignature(pem, file.case_id, file.merkle_root, file.signature.value)
    : false;
  const rootMatches = recomputed === file.merkle_root;
  return {
    valid: signatureValid && rootMatches && changedLeaves.length === 0,
    signatureValid,
    rootMatches,
    recomputedRoot: recomputed,
    changedLeaves,
    keyId: file.signature.key_id,
  };
}

/** Parse untrusted file text into a case export, or explain why it is not one. */
export function parseCaseFile(text: string): CaseExport {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error("The file is not JSON.");
  }
  const d = data as Partial<CaseExport>;
  if (
    typeof d !== "object" ||
    typeof d.case_id !== "number" ||
    typeof d.items !== "object" ||
    typeof d.leaves !== "object" ||
    typeof d.merkle_root !== "string" ||
    typeof d.signature?.value !== "string"
  ) {
    throw new Error("The file is not a Verita case-file export.");
  }
  return d as CaseExport;
}
