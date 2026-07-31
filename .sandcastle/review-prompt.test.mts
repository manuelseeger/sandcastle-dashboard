import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

function git(cwd: string, args: string[]): string {
  return execFileSync("git", args, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
}

test("review prompt uses a sandbox-local ref when its parent branch is unavailable", async () => {
  const repository = await mkdtemp(join(tmpdir(), "sandcastle-review-"));
  try {
    git(repository, ["init", "--quiet"]);
    git(repository, ["config", "user.name", "Test"]);
    git(repository, ["config", "user.email", "test@example.com"]);
    await writeFile(join(repository, "file.txt"), "base\n");
    git(repository, ["add", "file.txt"]);
    git(repository, ["commit", "--quiet", "-m", "base"]);
    const base = git(repository, ["rev-parse", "HEAD"]);

    await writeFile(join(repository, "file.txt"), "child\n");
    git(repository, ["commit", "--all", "--quiet", "-m", "child"]);
    assert.throws(() => git(repository, ["rev-parse", "--verify", "sandcastle/issue-1"]));

    git(repository, ["update-ref", "refs/sandcastle/review-target", base]);
    assert.doesNotThrow(() => git(repository, ["diff", "refs/sandcastle/review-target...HEAD"]));
    assert.match(git(repository, ["log", "refs/sandcastle/review-target..HEAD"]), /child/);

    const prompt = await readFile(join(process.cwd(), ".sandcastle", "review-prompt.md"), "utf8");
    assert.match(prompt, /git diff \{\{REVIEW_TARGET\}\}\.\.\.\{\{BRANCH\}\}/);
    assert.match(prompt, /git log \{\{REVIEW_TARGET\}\}\.\.\{\{BRANCH\}\}/);
    assert.doesNotMatch(prompt, /REVIEW_TARGET_BRANCH/);
  } finally {
    await rm(repository, { recursive: true, force: true });
  }
});
