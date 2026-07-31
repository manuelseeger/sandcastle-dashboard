/**
 * Helpers for verifying dependent merges before an isolated sandbox replays its
 * commits onto the host. Replay changes commit IDs, so host-side ancestry is
 * not a valid merge-success signal.
 */
export type GitCommandResult = { exitCode: number; stdout: string; stderr: string };

export type GitSandbox = {
  exec(command: string): Promise<GitCommandResult>;
};

export type MergeSource = {
  issueId: string;
  ref: string;
};

const issueIdPattern = /^\d+$/;
const commitPattern = /^[0-9a-f]{40}$/i;

export function mergeSourceRef(issueId: string): string {
  if (!issueIdPattern.test(issueId)) throw new Error(`invalid issue ID for merge source: ${issueId}`);
  return `refs/sandcastle/merge-source/${issueId}`;
}

/** Materialize exact host-selected dependent tips under sandbox-local refs. */
export async function prepareMergeSources(
  sandbox: GitSandbox,
  sources: Array<{ issueId: string; commit: string }>,
): Promise<MergeSource[]> {
  const prepared: MergeSource[] = [];
  for (const { issueId, commit } of sources) {
    if (!commitPattern.test(commit)) throw new Error(`invalid merge source commit for #${issueId}`);
    const ref = mergeSourceRef(issueId);
    const result = await sandbox.exec(`git update-ref ${ref} ${commit}`);
    if (result.exitCode !== 0) {
      throw new Error(`could not prepare merge source for #${issueId}: ${result.stderr.trim() || result.stdout.trim()}`);
    }
    prepared.push({ issueId, ref });
  }
  return prepared;
}

/**
 * Check merge ancestry in the sandbox, where the original source commits and
 * merge topology still exist. A nonzero merge-base result means that source
 * was not integrated; command execution errors are surfaced by the caller.
 */
export async function mergedSources(sandbox: GitSandbox, sources: MergeSource[]): Promise<Set<string>> {
  const merged = new Set<string>();
  for (const source of sources) {
    const result = await sandbox.exec(`git merge-base --is-ancestor ${source.ref} HEAD`);
    if (result.exitCode === 0) {
      merged.add(source.issueId);
    } else if (result.exitCode !== 1) {
      throw new Error(`could not verify merge source for #${source.issueId}: ${result.stderr.trim() || result.stdout.trim()}`);
    }
  }
  return merged;
}
