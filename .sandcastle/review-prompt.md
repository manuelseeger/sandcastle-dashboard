# TASK

Review issue {{TASK_ID}}: {{ISSUE_TITLE}} on branch `{{BRANCH}}`.

# ISSUE CONTEXT

<issue-context>

!`repo=${GH_REPO:?GH_REPO is required}; owner=${repo%/*}; name=${repo#*/}; gh api graphql -f query='query($owner:String!,$name:String!,$number:Int!) { repository(owner:$owner,name:$name) { issue(number:$number) { number title body labels(first:100) { nodes { name } } comments(first:100) { nodes { body } } parent { number title body labels(first:100) { nodes { name } } comments(first:100) { nodes { body } } } } } }' -F owner="$owner" -F name="$name" -F number={{TASK_ID}} --jq '.data.repository.issue'`

</issue-context>

# CHANGE CONTEXT

## Diff

!`git diff {{REVIEW_TARGET_BRANCH}}...{{BRANCH}}`

## Commits

!`git log {{REVIEW_TARGET_BRANCH}}..{{BRANCH}}`

# REVIEW PROCESS

Understand the issue, parent guidance, diff, and commits. Check correctness, acceptance criteria, edge cases, security, and appropriate test coverage. Follow repository instructions and run issue-appropriate verification. If fixes are needed and can be completed, apply and conventionally commit them.

Do not approve merely because the branch has commits. A no-diff issue may be complete if the target branch already satisfies it. If the issue cannot be validated as complete, preserve useful progress, leave a useful issue comment when appropriate, and do not output the completion promise.

Only when review is complete and the issue is satisfied, output:

<promise>COMPLETE</promise>
