# ISSUES

Here are the open issues labeled `sandcastle`, including immediate formal parent metadata:

<issues-json>

!`repo=${GH_REPO:?GH_REPO is required}; owner=${repo%/*}; name=${repo#*/}; gh api graphql -f query='query($owner:String!,$name:String!,$labels:[String!]) { repository(owner:$owner,name:$name) { issues(first:100,states:OPEN,labels:$labels,orderBy:{field:CREATED_AT,direction:ASC}) { nodes { number title body labels(first:100) { nodes { name } } comments(first:100) { nodes { body } } parent { number title body labels(first:100) { nodes { name } } comments(first:100) { nodes { body } } } } } } }' -F owner="$owner" -F name="$name" -F labels[]=sandcastle --jq '.data.repository.issues.nodes'`

</issues-json>

The list is the complete executable scope. Unlabeled parents are context only.

# TASK

Analyze the issues and build a dependency graph. Issue B is blocked by issue A when A is a formal sub-issue of B and both are executable issues, B requires A's code or infrastructure, the work is likely to conflict, or B depends on an API or decision from A.

A root is a top-level deliverable that is not a dependency or sub-issue of another executable issue. A standalone issue is its own root. The graph must be a forest: every issue belongs to exactly one root. Report cycles and dependencies shared by multiple roots as errors, skip those components, and continue with unrelated valid components.

An issue is ready when it has no blocking dependency among currently open executable issues. Re-evaluate on every run. Return only ready issues with their root ID and title. Do not choose branch names.

# OUTPUT

Always output JSON inside `<plan>` tags:

<plan>
{"issues":[{"id":"42","title":"Fix auth","rootId":"40","rootTitle":"Add accounts"}],"errors":[{"issueIds":["50","51"],"message":"Dependency cycle: #50 -> #51 -> #50"}]}
</plan>

Use empty arrays when there is no ready work or no errors.
