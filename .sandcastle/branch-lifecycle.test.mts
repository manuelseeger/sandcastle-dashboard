import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { worktreeForBranch } from "./branch-lifecycle.mts";

test("Sandcastle identifies the worktree checked out on a branch", () => {
  const worktrees = [
    "worktree /repo",
    "HEAD aaa",
    "branch refs/heads/main",
    "",
    "worktree /repo/.sandcastle/worktrees/sandcastle-issue-1",
    "HEAD bbb",
    "branch refs/heads/sandcastle/issue-1",
    "",
  ].join("\n");

  assert.equal(
    worktreeForBranch(worktrees, "sandcastle/issue-1"),
    "/repo/.sandcastle/worktrees/sandcastle-issue-1",
  );
  assert.equal(worktreeForBranch(worktrees, "sandcastle/issue-2"), undefined);
});

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

test("Sandcastle blocks root publication while its worktree has an interrupted git am", async () => {
  const source = await readFile(".sandcastle/main.mts", "utf8");
  const guard = source.indexOf("if (hasIncompleteAm(branch))");
  const publication = source.indexOf("push(branch);", guard);

  assert.ok(guard >= 0, "root setup must detect interrupted git am sessions");
  assert.ok(publication > guard, "root setup must check for git am before publication");
  assert.match(source, /has an interrupted git am session/);
});

test("Sandcastle discards a clean planner-only branch", async () => {
  const source = await readFile(".sandcastle/main.mts", "utf8");

  assert.match(source, /branchStrategy: \{ type: "branch", branch \}/);
  assert.match(source, /if \(result\.commits\.length \|\| result\.preservedWorktreePath\)/);
  assert.match(source, /git\(\["branch", "--delete", "--force", branch\]\)/);
});
