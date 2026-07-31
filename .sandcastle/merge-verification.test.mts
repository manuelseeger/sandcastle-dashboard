import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  mergeSourceRef,
  mergedSources,
  prepareMergeSources,
  type GitSandbox,
} from "./merge-verification.mts";

test("merge verification pins exact source commits and recognizes a partial sandbox merge", async () => {
  const commands: string[] = [];
  const sandbox: GitSandbox = {
    async exec(command) {
      commands.push(command);
      if (command.startsWith("git merge-base") && command.includes("merge-source/2")) return { exitCode: 0, stdout: "", stderr: "" };
      if (command.startsWith("git merge-base") && command.includes("merge-source/3")) return { exitCode: 1, stdout: "", stderr: "" };
      return { exitCode: 0, stdout: "", stderr: "" };
    },
  };

  const sources = await prepareMergeSources(sandbox, [
    { issueId: "2", commit: "a".repeat(40) },
    { issueId: "3", commit: "b".repeat(40) },
  ]);
  const merged = await mergedSources(sandbox, sources);

  assert.deepEqual(sources, [
    { issueId: "2", ref: "refs/sandcastle/merge-source/2" },
    { issueId: "3", ref: "refs/sandcastle/merge-source/3" },
  ]);
  assert.deepEqual([...merged], ["2"]);
  assert.deepEqual(commands, [
    `git update-ref refs/sandcastle/merge-source/2 ${"a".repeat(40)}`,
    `git update-ref refs/sandcastle/merge-source/3 ${"b".repeat(40)}`,
    "git merge-base --is-ancestor refs/sandcastle/merge-source/2 HEAD",
    "git merge-base --is-ancestor refs/sandcastle/merge-source/3 HEAD",
  ]);
});

test("merge verification rejects unsafe issue IDs and invalid commit IDs", async () => {
  const sandbox: GitSandbox = { async exec() { return { exitCode: 0, stdout: "", stderr: "" }; } };

  assert.throws(() => mergeSourceRef("2; rm -rf /"), /invalid issue ID/);
  await assert.rejects(prepareMergeSources(sandbox, [{ issueId: "2", commit: "not-a-commit" }]), /invalid merge source commit/);
});

test("merge orchestration awaits sandbox ancestry verification before cleanup", async () => {
  const source = await readFile(".sandcastle/main.mts", "utf8");
  const verification = source.indexOf("const verifiedSources = await mergedSources(sandbox, sources);");
  const cleanup = source.indexOf("await sandbox.close();", verification);

  assert.ok(verification >= 0, "merge verification must be awaited");
  assert.ok(cleanup > verification, "sandbox cleanup must follow merge verification");
  assert.match(source, /merger completed but did not verify any dependent source as merged/);
});

test("merge prompt instructs the agent to merge only orchestration-pinned source refs", async () => {
  const prompt = await readFile(".sandcastle/merge-prompt.md", "utf8");

  assert.match(prompt, /dependent source refs/);
  assert.match(prompt, /exact dependent commits selected by orchestration/);
  assert.match(prompt, /git merge <source-ref> --no-edit/);
  assert.doesNotMatch(prompt, /git merge <branch> --no-edit/);
});
