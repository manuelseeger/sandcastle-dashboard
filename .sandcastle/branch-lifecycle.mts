/** Locate the worktree currently checked out on a local branch. */
export function worktreeForBranch(
  porcelain: string,
  branch: string,
): string | undefined {
  const target = `branch refs/heads/${branch}`;
  for (const record of porcelain.trim().split("\n\n")) {
    const lines = record.split("\n");
    const worktree = lines.find((line) => line.startsWith("worktree "));
    if (worktree && lines.includes(target)) {
      return worktree.slice("worktree ".length);
    }
  }
  return undefined;
}
