// Root-PR Sandcastle orchestration
//
// This workflow repeatedly performs four phases:
//   1. Plan: inspect every open issue labeled `sandcastle`, infer a forest of
//      dependencies, and return only the issues that are ready now.
//   2. Prepare + execute: publish/reuse one aggregation branch and PR per root,
//      then run an implementer and reviewer for every ready issue in parallel.
//   3. Merge: group completed dependent issues by root and integrate each
//      root's branches sequentially, while processing different roots in parallel.
//   4. Finalize: push merged roots and close dependents, or make a completed
//      root PR ready and remove the root's `sandcastle` label.
//
// The loop replans after every progress-making round so closing dependents can
// unblock their parents. Local branches and remote root PRs are deliberately
// reusable, allowing a later serialized invocation to resume unfinished work.
// Git/GitHub lifecycle operations stay here rather than in agent prompts so
// branch naming, publication, PR state, and issue closure remain deterministic.
//
// Usage:
//   npm run sandcastle

import { execFileSync } from "node:child_process";
import * as sandcastle from "@ai-hero/sandcastle";
import { withDockerSbxProvider, type DockerSbxOptions } from "./docker-sbx-provider.mts";
import { z } from "zod";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

// Agents must explicitly emit this exact marker. A successful process exit or
// a newly-created commit is not enough to advance an issue through the workflow.
const COMPLETE = "<promise>COMPLETE</promise>";

// Reserve the higher-capacity model for work that coordinates or integrates
// multiple issues; individual implementation and review use the standard one.
const highCapAgent = sandcastle.claudeCode("claude-opus-5");
const standardAgent = sandcastle.claudeCode("claude-sonnet-5");

// Bound iterative replanning so a malformed or constantly-changing backlog
// cannot keep one scheduled invocation alive indefinitely.
const MAX_ITERATIONS = Number(process.env.SANDCASTLE_MAX_ITERATIONS ?? 1);

if (!Number.isInteger(MAX_ITERATIONS) || MAX_ITERATIONS < 1) {
  throw new Error("SANDCASTLE_MAX_ITERATIONS must be a positive integer");
}

// Every Sandcastle phase runs in an sbx microVM. Defaults match the local
// template build and the spike-proven 4 CPU / 8 GiB castle size.
function sbxOptions(scope: string): DockerSbxOptions {
  const cpus = Number(process.env.SANDCASTLE_SBX_CPUS ?? 4);
  const memory = process.env.SANDCASTLE_SBX_MEMORY ?? "8g";
  // A full implementation/review pipeline can include dependency install,
  // browser verification, and a large agent turn. Ten minutes is too short
  // for that work in a microVM; callers may still set a tighter CI limit.
  const timeoutMs = Number(process.env.SANDCASTLE_SBX_TIMEOUT_MS ?? 30 * 60_000);
  if (!Number.isInteger(cpus) || cpus < 1 || !/^\d+(?:[gGmM])$/.test(memory) || !Number.isSafeInteger(timeoutMs) || timeoutMs < 1) {
    throw new Error("SANDCASTLE_SBX_CPUS, SANDCASTLE_SBX_MEMORY, and SANDCASTLE_SBX_TIMEOUT_MS must be positive");
  }
  return {
    template: process.env.SANDCASTLE_SBX_TEMPLATE?.trim() || "parames-sbx:dev",
    namePrefix: `parames-${process.env.SANDCASTLE_DEPLOYMENT_ID?.trim() || "local"}-${process.env.SANDCASTLE_INVOCATION_ID?.trim() || process.pid}-${scope}`,
    cpus,
    memory,
    timeoutMs,
    // Isolated Git transfer intentionally does not rely on a guest remote.
    // GH_REPO lets every guest-side gh command identify this repository.
    env: { GH_REPO: githubRepository },
  };
}

// Resolve repository identity on the trusted host, where the checkout remote is
// available, then pass only that public identifier into each microVM.
const githubRepository = process.env.SANDCASTLE_GH_REPO?.trim()
  || process.env.GH_REPO?.trim()
  || gh(["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"]);
if (!/^[^/\s]+\/[^/\s]+$/.test(githubRepository)) {
  throw new Error("SANDCASTLE_GH_REPO must be an owner/repository identifier");
}

// Application dependencies are installed in every executable microVM sandbox.
// Implementer and reviewer share one sandbox, so these commands run once for
// that complete issue pipeline.
const hooks = {
  sandbox: {
    onSandboxReady: [
      { command: "uv sync --locked" },
      { command: "npm ci --prefix webapp" },
      { command: "npm ci --prefix aspire" },
      { command: "cd aspire && aspire restore --non-interactive" },
    ],
  },
};

// ---------------------------------------------------------------------------
// Planner output contract
// ---------------------------------------------------------------------------

// Output.object extracts JSON from the planner's <plan> block and validates it.
// IDs stay as strings because GitHub issue numbers are prompt/orchestration
// identifiers rather than values on which this script performs arithmetic.
const planSchema = z.object({
  issues: z.array(
    z.object({
      id: z.string().regex(/^\d+$/),
      title: z.string(),
      rootId: z.string().regex(/^\d+$/),
      rootTitle: z.string(),
    }),
  ),
  errors: z.array(
    z.object({
      issueIds: z.array(z.string().regex(/^\d+$/)),
      message: z.string(),
    }),
  ),
});

// Derive the issue type from the runtime schema so validation and TypeScript
// cannot silently drift apart.
type Issue = z.infer<typeof planSchema>["issues"][number];

// Root metadata is resolved once per planning round and carries the canonical
// branch plus the PR required by all later lifecycle actions.
type Root = { id: string; title: string; branch: string; pr: PullRequest };

// This is the exact subset requested from `gh pr list`. Both `state` and
// `mergedAt` are retained because GitHub reports merged PRs as closed.
type PullRequest = {
  number: number;
  state: string;
  isDraft: boolean;
  body: string;
  baseRefName: string;
  mergedAt: string | null;
};

// ---------------------------------------------------------------------------
// Process, Git, and GitHub helpers
// ---------------------------------------------------------------------------

// Run argv directly without a shell. This prevents issue titles, branch names,
// and generated PR text from being interpreted as shell syntax. Most failures
// are fatal to the affected pipeline; expected probes can request an empty
// result with allowFailure.
function command(command: string, args: string[], allowFailure = false): string {
  try {
    return execFileSync(command, args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
  } catch (error) {
    if (allowFailure) return "";
    const details = error as { stderr?: Buffer; message: string };
    throw new Error(`${command} ${args.join(" ")} failed: ${details.stderr?.toString().trim() || details.message}`);
  }
}

// Keep Git invocations concise and give every failure the same diagnostics.
function git(args: string[], allowFailure = false): string {
  return command("git", args, allowFailure);
}

// Keep GitHub CLI invocations concise and consistently authenticated by the
// GH_TOKEN inherited from `.sandcastle/.env`.
function gh(args: string[], allowFailure = false): string {
  return command("gh", args, allowFailure);
}

// Branch names are an orchestration decision, never an agent decision. The
// deterministic format is what makes retries find accumulated local work.
function branchFor(id: string): string {
  return `sandcastle/issue-${id}`;
}

// Probe an exact full ref. `git branch --list` would be ambiguous between
// local and remote refs, which have different publication semantics here.
function branchExists(ref: string): boolean {
  try {
    execFileSync("git", ["show-ref", "--verify", "--quiet", ref], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

// Ancestry is used both for safe fast-forward synchronization and as the
// mechanical source of truth for whether a dependent branch was merged.
function isAncestor(ancestor: string, descendant: string): boolean {
  try {
    execFileSync("git", ["merge-base", "--is-ancestor", ancestor, descendant], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

// Publish only the named branch to the same remote branch. No force option is
// ever used: remote rejection safely stops closure/finalization for that root.
function push(branch: string): void {
  git(["push", "origin", `refs/heads/${branch}:refs/heads/${branch}`]);
}

// ---------------------------------------------------------------------------
// Root branch and pull-request lifecycle
// ---------------------------------------------------------------------------

// Create the one deterministic empty commit needed when a brand-new root branch
// still equals its configured base. A temporary worktree lets this script commit
// on that branch without changing the operator's current checkout. Author data
// is command-scoped so repository/user Git configuration remains untouched.
function initializeRootBranch(rootId: string, branch: string): void {
  const worktree = `.sandcastle/root-initialization-${rootId}`;
  git(["worktree", "add", "--force", worktree, branch]);
  try {
    git([
      "-C", worktree, "-c", "user.name=Sandcastle", "-c", "user.email=sandcastle@users.noreply.github.com",
      "commit", "--allow-empty", "-m", `chore: initialize Sandcastle work for #${rootId}`,
    ]);
  } finally {
    // Cleanup is best-effort because preserving the original commit/build error
    // is more useful than replacing it with a secondary cleanup error.
    git(["worktree", "remove", "--force", worktree], true);
  }
}

// Use an explicit base when requested; otherwise ask GitHub for the repository
// default. Never use the host's checked-out branch, which may be unrelated.
function getBaseBranch(): string {
  const configured = process.env.SANDCASTLE_BASE_BRANCH?.trim();
  return configured || gh(["repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"]);
}

// Search every PR state for this head branch. Including closed/merged PRs is
// essential: creating a replacement for a closed-unmerged PR would bypass the
// workflow's required manual-intervention stop.
function lookupPullRequest(branch: string): PullRequest | undefined {
  const output = gh(["pr", "list", "--head", branch, "--state", "all", "--limit", "100", "--json", "number,state,isDraft,body,baseRefName,mergedAt"]);
  const prs = JSON.parse(output) as PullRequest[];
  return prs[0];
}

// Ensure GitHub will close the root issue when the PR merges. Existing human
// content is preserved verbatim and the exact closure line is only appended
// when absent.
function ensureClosureLine(pr: PullRequest, rootId: string): PullRequest {
  const closure = `Closes #${rootId}`;
  if (pr.body.split("\n").includes(closure)) return pr;
  const body = `${pr.body.trimEnd()}\n\n${closure}`.trim();
  gh(["pr", "edit", String(pr.number), "--body", body]);
  return { ...pr, body };
}

// Reconcile one root's local branch, published branch, and PR into a usable
// state. Returning undefined stops only this root, allowing unrelated roots to
// continue. Thrown publication/API failures are isolated by the caller.
function ensureRoot(rootId: string, rootTitle: string, baseBranch: string): Root | undefined {
  const branch = branchFor(rootId);
  const remote = `refs/remotes/origin/${branch}`;
  git(["fetch", "origin", baseBranch, branch], true);

  const hasLocal = branchExists(`refs/heads/${branch}`);
  const hasRemote = branchExists(remote);

  // Existing local and remote roots may only synchronize by fast-forward. If
  // remote is ahead, update the local ref safely. If local is ahead, preserve it
  // for the later normal push. If neither contains the other, stop this root.
  if (hasLocal && hasRemote) {
    if (isAncestor(branch, `origin/${branch}`)) {
      git(["update-ref", `refs/heads/${branch}`, `refs/remotes/origin/${branch}`]);
    } else if (!isAncestor(`origin/${branch}`, branch)) {
      console.error(`  ✗ root #${rootId}: local and remote ${branch} have diverged`);
      return undefined;
    }
  } else if (hasRemote) {
    // A published root without a local branch is resumed from the remote tip.
    git(["branch", branch, `origin/${branch}`]);
  } else if (!hasLocal) {
    // A genuinely new root starts from the freshly fetched configured base.
    git(["branch", branch, `origin/${baseBranch}`]);
  }

  // Look up the PR before initializing so retries never add another empty
  // commit to an already-published root.
  let pr = lookupPullRequest(branch);
  // A new PR needs a distinct head. Once made, this commit makes the branch
  // differ from the base branch, so retries cannot create a duplicate.
  if (!pr && isAncestor(branch, `origin/${baseBranch}`) && isAncestor(`origin/${baseBranch}`, branch)) {
    initializeRootBranch(rootId, branch);
  }
  // Root branches are the only issue branches published to GitHub. Pushing
  // before PR creation also makes the head selectable by `gh pr create`.
  push(branch);

  // Re-query after publication because another interrupted invocation may have
  // created the PR between the first lookup and this point.
  pr = lookupPullRequest(branch);
  // A merged PR means the root is finished. A closed but unmerged PR requires
  // an owner decision and must never be silently replaced.
  if (pr?.mergedAt) return { id: rootId, title: rootTitle, branch, pr };
  if (pr && pr.state === "CLOSED") {
    console.error(`  ✗ root #${rootId}: PR #${pr.number} was closed without merging`);
    return undefined;
  }
  // Reused PRs must target the configured base as well as new ones.
  if (pr && pr.baseRefName !== baseBranch) {
    gh(["pr", "edit", String(pr.number), "--base", baseBranch]);
    pr = { ...pr, baseRefName: baseBranch };
  }
  // New roots immediately receive a draft aggregation PR. Existing open draft
  // and ready PRs are reused without changing their draft state.
  if (!pr) {
    const body = `Sandcastle is tracking this root issue.\n\nCloses #${rootId}`;
    gh([
      "pr", "create", "--draft", "--base", baseBranch, "--head", branch,
      "--title", `#${rootId}: ${rootTitle}`, "--body", body,
    ]);
    pr = lookupPullRequest(branch);
    if (!pr) throw new Error(`created root PR for #${rootId} could not be found`);
  }
  return { id: rootId, title: rootTitle, branch, pr: ensureClosureLine(pr, rootId) };
}

// Create a dependent branch from the latest local root tip only on its first
// attempt. Existing dependent branches are deliberately reused unchanged so a
// retry does not merge newer root work into partially completed issue work.
function ensureDependentBranch(issue: Issue, root: Root): string {
  const branch = branchFor(issue.id);
  if (!branchExists(`refs/heads/${branch}`)) git(["branch", branch, root.branch]);
  return branch;
}

// ---------------------------------------------------------------------------
// Issue implementation and review pipeline
// ---------------------------------------------------------------------------

// Run the implementer and reviewer in one shared sandbox. Completion requires
// both explicit promises, even when no commit or diff is produced: a retry may
// already contain valid work, or the target branch may already satisfy an issue.
async function runIssue(issue: Issue, root: Root, baseBranch: string): Promise<{ issue: Issue; branch: string; root: Root }> {
  // Root issues run directly on their aggregation branch. Dependents run on
  // their private local branch and are integrated in the merge phase.
  const branch = issue.id === root.id ? root.branch : ensureDependentBranch(issue, root);

  // Review roots against the remote configured base and dependents against the
  // complete local root branch, matching the user-visible integration diff.
  const target = issue.id === root.id ? `origin/${baseBranch}` : root.branch;

  // One provider scope owns exactly one shared castle for the complete issue
  // pipeline. Its finally cleanup cannot affect a concurrently executing issue.
  return withDockerSbxProvider(sbxOptions(`issue-${issue.id}`), async (provider) => {
    const sandbox = await sandcastle.createSandbox({ branch, sandbox: provider, hooks });
    try {
      const implement = await sandbox.run({
        name: `implementer-${issue.id}`, maxIterations: 100, agent: standardAgent,
        promptFile: "./.sandcastle/implement-prompt.md", completionSignal: COMPLETE,
        promptArgs: { TASK_ID: issue.id, ISSUE_TITLE: issue.title, ROOT_ID: root.id, ROOT_TITLE: root.title, ROOT_BRANCH: root.branch, BRANCH: branch },
      });
      if (implement.completionSignal !== COMPLETE) throw new Error("implementer did not complete");
      const review = await sandbox.run({
        name: `reviewer-${issue.id}`, maxIterations: 100, agent: standardAgent,
        promptFile: "./.sandcastle/review-prompt.md", completionSignal: COMPLETE,
        promptArgs: { TASK_ID: issue.id, ISSUE_TITLE: issue.title, BRANCH: branch, REVIEW_TARGET_BRANCH: target },
      });
      if (review.completionSignal !== COMPLETE) throw new Error("reviewer did not complete");
      const status = await sandbox.exec("git status --porcelain");
      if (status.exitCode !== 0 || status.stdout.trim()) throw new Error("agent left the worktree dirty");
      return { issue, branch, root };
    } finally {
      await sandbox.close();
    }
  });
}

// ---------------------------------------------------------------------------
// Per-root dependent merge pipeline
// ---------------------------------------------------------------------------

// Give one merger exclusive access to a root branch. It processes that root's
// dependents sequentially, while the main loop runs merger sandboxes for
// unrelated roots concurrently. The returned IDs are mechanically verified as
// merged and safely published/closed.
async function mergeRoot(root: Root, completed: Array<{ issue: Issue; branch: string }>): Promise<string[]> {
  // The merger works directly on the local root aggregation branch; it does
  // not create a separate synthetic merge branch.
  await withDockerSbxProvider(sbxOptions(`merge-${root.id}`), async (provider) => {
  const sandbox = await sandcastle.createSandbox({ branch: root.branch, sandbox: provider, hooks });
  try {
    const result = await sandbox.run({
      name: `merger-${root.id}`,
      maxIterations: 100,
      agent: highCapAgent,
      promptFile: "./.sandcastle/merge-prompt.md",
      completionSignal: COMPLETE,
      promptArgs: {
        ROOT_BRANCH: root.branch,
        BRANCHES: completed.map(({ branch }) => `- ${branch}`).join("\n"),
        ISSUE_IDS: completed.map(({ issue }) => issue.id).join(","),
      },
    });
    // Publishing is forbidden unless the agent explicitly completed and left
    // the root clean. A partial batch is valid as long as these conditions hold.
    const status = await sandbox.exec("git status --porcelain");
    if (result.completionSignal !== COMPLETE || status.exitCode !== 0 || status.stdout.trim()) {
      throw new Error("merger did not complete with a clean root worktree");
    }
  } finally {
    await sandbox.close();
  }
  });

  // Agent output does not decide merge success. A dependent's exact tip must
  // be an ancestor of the final root tip, naturally supporting partial batches.
  const merged = completed.filter(({ branch }) => isAncestor(branch, root.branch));
  if (!merged.length) return [];

  // Publication is the transaction boundary for issue closure. If this normal
  // push fails, the function throws before any dependent issue is closed.
  push(root.branch);
  // Progress comments are informational and intentionally best-effort. The MVP
  // allows duplicate comments on retries, so comment failure does not block
  // closure after a successful push.
  gh(["pr", "comment", String(root.pr.number), "--body", `Sandcastle merged this round: ${merged.map(({ issue }) => `#${issue.id}`).join(", ")}.`], true);

  // Closing verified dependents changes the next planner input and reveals the
  // following layer of the dependency graph.
  for (const { issue } of merged) {
    gh(["issue", "close", issue.id, "--comment", `Completed by Sandcastle and merged into root PR #${root.pr.number}.`]);
  }
  return merged.map(({ issue }) => issue.id);
}

// Finalize a root only after its own implementer and reviewer complete. Push
// first, preserve an already-ready PR, and remove the execution label without
// closing the root issue; the PR's closure line handles that on merge.
function completeRoot(root: Root): void {
  push(root.branch);
  if (root.pr.isDraft) gh(["pr", "ready", String(root.pr.number)]);
  gh(["issue", "edit", root.id, "--remove-label", "sandcastle"]);
}

// ---------------------------------------------------------------------------
// Iterative orchestration loop
// ---------------------------------------------------------------------------

// Collect run-wide diagnostics for the concise final summary. A set avoids
// repeating the same unfinished root across planning rounds.
const unfinished = new Set<string>();
const errors: string[] = [];

// Re-plan after every progress-making execution/merge round. This is what lets
// newly closed dependencies unblock their parent in the same invocation.
for (let iteration = 1; iteration <= MAX_ITERATIONS; iteration++) {
  console.log(`\n=== Iteration ${iteration}/${MAX_ITERATIONS} ===`);

  // -------------------------------------------------------------------------
  // Phase 1: Plan the complete currently-open labeled issue set
  // -------------------------------------------------------------------------

  let plan: z.infer<typeof planSchema>;
  try {
    const result = await withDockerSbxProvider(sbxOptions(`planner-${iteration}`), (provider) => sandcastle.run({
      hooks: {}, sandbox: provider, name: "planner", maxIterations: 1,
      agent: highCapAgent, promptFile: "./.sandcastle/plan-prompt.md",
      output: sandcastle.Output.object({ tag: "plan", schema: planSchema }),
    }));
    plan = result.output;
  } catch (error) {
    // Without validated structured output there is no safe branch/root mapping,
    // so stop this invocation rather than guessing.
    errors.push(`planner: ${String(error)}`);
    break;
  }

  // Invalid graph components are reported but do not prevent valid unrelated
  // roots returned in the same plan from continuing.
  for (const error of plan.errors) {
    const message = `planner skipped #${error.issueIds.join(", #")}: ${error.message}`;
    errors.push(message);
    console.error(`  ✗ ${message}`);
  }
  // An empty ready set is a clean terminal/no-progress condition.
  if (!plan.issues.length) break;

  // -------------------------------------------------------------------------
  // Phase 2: Detect the configured base and prepare every affected root branch/PR
  // -------------------------------------------------------------------------

  const baseBranch = getBaseBranch();
  git(["fetch", "origin", baseBranch]);
  // Key roots by planner-provided ID so multiple ready dependents share one
  // publication/PR reconciliation operation during this round.
  const roots = new Map<string, Root>();
  for (const issue of plan.issues) {
    if (roots.has(issue.rootId)) continue;
    try {
      // Publication, divergence, and closed-PR failures are isolated per root.
      const root = ensureRoot(issue.rootId, issue.rootTitle, baseBranch);
      if (root?.pr.mergedAt) continue;
      if (root) roots.set(root.id, root);
      else unfinished.add(issue.rootId);
    } catch (error) {
      const message = `root #${issue.rootId}: ${String(error)}`;
      errors.push(message);
      unfinished.add(issue.rootId);
      console.error(`  ✗ ${message}`);
    }
  }

  // -------------------------------------------------------------------------
  // Phase 3: Implement and review every ready issue in parallel
  // -------------------------------------------------------------------------

  // Issues whose root could not be prepared are skipped for this round.
  // allSettled prevents one agent/castle failure from cancelling other roots.
  const executable = plan.issues.filter((issue) => roots.has(issue.rootId));
  const settled = await Promise.allSettled(
    executable.map((issue) => runIssue(issue, roots.get(issue.rootId)!, baseBranch)),
  );
  // Separate completed root work from completed dependent work. Dependents must
  // be grouped for merger agents; roots skip merging and go to PR finalization.
  const completedDependents = new Map<string, Array<{ issue: Issue; branch: string }>>();
  const completedRoots: Root[] = [];
  for (const [index, outcome] of settled.entries()) {
    const issue = executable[index]!;
    if (outcome.status === "rejected") {
      const message = `#${issue.id}: ${String(outcome.reason)}`;
      errors.push(message);
      unfinished.add(issue.rootId);
      console.error(`  ✗ ${message}`);
      continue;
    }
    if (issue.id === issue.rootId) completedRoots.push(roots.get(issue.rootId)!);
    else {
      const dependencies = completedDependents.get(issue.rootId) ?? [];
      dependencies.push({ issue, branch: outcome.value.branch });
      completedDependents.set(issue.rootId, dependencies);
    }
  }

  // -------------------------------------------------------------------------
  // Phase 4: Merge dependents per root and finalize directly completed roots
  // -------------------------------------------------------------------------

  // Progress controls whether another planner iteration is worthwhile. Agent
  // completion alone is not progress: a dependent must publish/close, or a root
  // must publish/be made ready/have its label removed.
  let progress = false;

  // One merger handles each root's branches sequentially; roots run in parallel.
  const merges = await Promise.allSettled([...completedDependents.entries()].map(async ([rootId, issues]) => {
    const merged = await mergeRoot(roots.get(rootId)!, issues);
    return { rootId, merged };
  }));
  // A fulfilled merger only counts as progress when ancestry verification found
  // and published at least one dependent branch.
  for (const merge of merges) {
    if (merge.status === "fulfilled") progress ||= merge.value.merged.length > 0;
    else errors.push(`merge: ${String(merge.reason)}`);
  }

  // Roots become ready independently, so finalize every successful root even if
  // another root or merge pipeline failed in the same round.
  for (const root of completedRoots) {
    try {
      completeRoot(root);
      progress = true;
    } catch (error) {
      errors.push(`root #${root.id}: ${String(error)}`);
      unfinished.add(root.id);
    }
  }

  // Stop after a no-progress round instead of repeatedly sending agents the
  // same blocked/incomplete work. A future serialized invocation can resume it.
  if (!progress) break;
}

// ---------------------------------------------------------------------------
// Concise resumability summary
// ---------------------------------------------------------------------------

console.log("\nSandcastle run complete.");
if (unfinished.size) console.log(`Unfinished roots: ${[...unfinished].map((id) => `#${id}`).join(", ")}`);
if (errors.length) console.log(`Errors: ${errors.join(" | ")}`);
