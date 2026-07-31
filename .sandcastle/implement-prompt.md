# TASK

Fix issue {{TASK_ID}}: {{ISSUE_TITLE}}

Only work on this issue. Work on branch {{BRANCH}} and make conventional commits.

# ISSUE CONTEXT

The following is deterministic GitHub context for this issue and its immediate formal parent:

<issue-context>

!`repo=${GH_REPO:?GH_REPO is required}; owner=${repo%/*}; name=${repo#*/}; gh api graphql -f query='query($owner:String!,$name:String!,$number:Int!) { repository(owner:$owner,name:$name) { issue(number:$number) { number title body labels(first:100) { nodes { name } } comments(first:100) { nodes { body } } parent { number title body labels(first:100) { nodes { name } } comments(first:100) { nodes { body } } } } } }' -F owner="$owner" -F name="$name" -F number={{TASK_ID}} --jq '.data.repository.issue'`

</issue-context>

# CONTEXT

Root issue: #{{ROOT_ID}} — {{ROOT_TITLE}}
Root branch: {{ROOT_BRANCH}}

<recent-commits>

!`git log -n 10 --format="%H%n%ad%n%B---" --date=short`

</recent-commits>

# EXECUTION

Explore the repository and relevant tests before changing code. Follow `AGENTS.md`, repository documentation, and issue/parent guidance. If applicable, use red-green-refactor. Choose and run verification appropriate to this issue.

If the task is incomplete, preserve progress, leave a useful issue comment, and do not output the completion promise. Only when the issue is semantically complete, output:

<promise>COMPLETE</promise>

# FINAL RULE

ONLY WORK ON THIS SINGLE ISSUE.
