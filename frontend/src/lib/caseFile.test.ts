import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { canonicalize, merkleRoot, parseCaseFile, verifyCaseFile } from "./caseFile";

// Files signed by the Python backend (backend/scripts/make_case_export_fixture.py): the browser must
// reach the same verdicts, root and leaves.
const dir = join(__dirname, "../test/fixtures");
const text = (name: string) => readFileSync(join(dir, name), "utf-8");

describe("canonicalize (RFC 8785)", () => {
  it("matches the RFC's §3.2.2 example", () => {
    const raw =
      '{"numbers":[333333333.33333329,1E30,4.50,2e-3,0.000000000000000000000000001],' +
      '"string":"\\u20ac$\\u000F\\u000aA\'\\u0042\\u0022\\u005c\\\\\\"\\/",' +
      '"literals":[null,true,false]}';
    expect(canonicalize(JSON.parse(raw))).toBe(
      '{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],' +
        '"string":"€$\\u000f\\nA\'B\\"\\\\\\\\\\"/"}',
    );
  });

  it("sorts keys by UTF-16 code units", () => {
    expect(canonicalize({ דּ: 1, "\u{1f600}": 2, a: 0 })).toBe('{"a":0,"\u{1f600}":2,"דּ":1}');
  });

  it("rejects non-JSON numbers", () => {
    expect(() => canonicalize(Number.NaN)).toThrow();
    expect(canonicalize(-0)).toBe("0");
  });
});

describe("verifyCaseFile", () => {
  it("accepts the Python-signed export and recomputes the same root and leaves", async () => {
    const file = parseCaseFile(text("case-export.json"));
    const { root, leaves } = await merkleRoot(file.items);
    expect(root).toBe(file.merkle_root);
    expect(leaves).toEqual(file.leaves);
    const check = await verifyCaseFile(file);
    expect(check).toMatchObject({
      valid: true,
      signatureValid: true,
      rootMatches: true,
      changedLeaves: [],
    });
  });

  it("names the changed leaf in the tampered copy", async () => {
    const check = await verifyCaseFile(parseCaseFile(text("case-export-tampered.json")));
    expect(check.valid).toBe(false);
    expect(check.changedLeaves).toEqual(["EV-TXN-102"]);
    expect(check.rootMatches).toBe(false);
    expect(check.signatureValid).toBe(true); // the signature is fine; the content is not
  });

  it("fails with the wrong key and on a forged root", async () => {
    const file = parseCaseFile(text("case-export.json"));
    const other = parseCaseFile(text("case-export.json"));
    const forged = { ...other, merkle_root: "00".repeat(32) };
    expect((await verifyCaseFile(forged)).signatureValid).toBe(false);
    const garbage = "-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----";
    expect((await verifyCaseFile(file, garbage)).valid).toBe(false);
    const noKey = { ...file, public_key_pem: null };
    expect((await verifyCaseFile(noKey)).signatureValid).toBe(false);
  });

  it("explains files that are not case files", () => {
    expect(() => parseCaseFile("not json")).toThrow("not JSON");
    expect(() => parseCaseFile('{"hello": 1}')).toThrow("not a Verita case-file export");
  });

  it("handles an empty item set", async () => {
    const { root } = await merkleRoot({});
    expect(root).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  });
});
