# TASK

Merge these dependent branches into root branch `{{ROOT_BRANCH}}`:

{{BRANCHES}}

The sandbox is already on the root branch. Only integrate the listed branches; do not push branches, create or edit PRs, post comments, or close issues. Orchestration handles GitHub lifecycle actions.

# ISSUE CONTEXT

The following deterministic GitHub context contains the open issue set. Focus on root/dependent IDs `{{ISSUE_IDS}}` and their immediate formal parents:

<issues-context>

!`repo=${GH_REPO:?GH_REPO is required}; owner=${repo%/*}; name=${repo#*/}; gh api graphql -f query='query($owner:String!,$name:String!) { repository(owner:$owner,name:$name) { issues(first:100,states:OPEN,orderBy:{field:CREATED_AT,direction:ASC}) { nodes { number title body labels(first:100) { nodes { name } } comments(first:100) { nodes { body } } parent { number title body labels(first:100) { nodes { name } } comments(first:100) { nodes { body } } } } } } }' -F owner="$owner" -F name="$name" --jq '.data.repository.issues.nodes'`

</issues-context>

# MERGE PROCESS

For each branch, run `git merge <branch> --no-edit`. Resolve conflicts using issue and repository context and run validation appropriate to the integrated work. If an individual merge cannot be completed safely, abort that merge so the root is clean, then continue with other branches when safe.

Use normal Git merge behavior. Do not squash, force `--no-ff`, or create a synthetic summary commit. Before completion, ensure the root worktree is clean and all successful integration work is committed. Partial success is valid.

Only when this merge attempt and validation are finished, output:

<promise>COMPLETE</promise>
