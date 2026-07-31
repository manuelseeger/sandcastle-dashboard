import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Sandcastle issue branches do not inherit the base branch upstream", async () => {
  const source = await readFile(".sandcastle/main.mts", "utf8");

  assert.match(source, /git\(\["branch", "--no-track", branch, `origin\/\$\{baseBranch\}`\]\)/);
  assert.match(source, /git\(\["branch", "--no-track", branch, root\.branch\]\)/);
  assert.match(source, /git\(\["branch", "--track", branch, `origin\/\$\{branch\}`\]\)/);
});

test("Sandcastle publication assigns a root branch to its same-named remote upstream", async () => {
  const source = await readFile(".sandcastle/main.mts", "utf8");

  assert.match(
    source,
    /git\(\["push", "--set-upstream", "origin", `refs\/heads\/\$\{branch\}:refs\/heads\/\$\{branch\}`\]\)/,
  );
});
