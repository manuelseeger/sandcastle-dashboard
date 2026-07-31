# Sandcastle host dashboard information research

## Summary

This document records information available to a dashboard running on the same host as Sandcastle. The research covered the running Sandcastle process, Sandcastle 0.12.0 APIs, generated logs, Git worktrees, and Docker Sandboxes (`sbx` 0.37.0).

A useful first dashboard can be built without entering the VMs. Its strongest data sources are:

1. The host process tree
2. `sbx` JSON commands
3. `.sandcastle/logs/*.log`
4. Git worktree and branch metadata
5. Optional GitHub lookups

## Information available now

### 1. Sandcastle host processes

From `/proc` or `ps`, the dashboard can discover:

- npm launcher PID
- `tsx` wrapper PID
- Actual orchestration Node PID
- Start time and elapsed time
- Running, sleeping, or zombie status
- CPU time and current CPU percentage
- Resident and virtual memory
- Thread count
- Child processes
- Working directory and repository
- Process group and session, useful for identifying one invocation

A running hierarchy is effectively:

```text
npm run sandcastle
└── tsx .sandcastle/main.mts
    └── node .sandcastle/main.mts
        └── sbx exec ... claude ...
```

The Node PID is also embedded in default VM names, providing correlation when no explicit invocation ID is configured.

#### Limitations

A separately started dashboard can detect whether a process exists, but cannot reliably obtain its eventual exit code because it is not the process parent. A persistent run record would eventually be needed to distinguish:

- Completed successfully
- Failed
- Interrupted
- Killed
- Host rebooted

Process command lines currently contain injected credential values. The dashboard must **never expose or store complete command lines or environments**. It should read only allowlisted, redacted fields.

### 2. VM/castle inventory

`sbx ls --json` supplies:

- Sandbox name
- Stable sandbox UUID
- Agent type, such as `claude`
- Status, such as `running` or `stopped`
- Host workspace path
- Whether the workspace is missing
- Published ports, when present

`sbx inspect <name> --json` adds:

- VM state
- VM uptime
- Template/image name
- Image digest
- Authentication mode
- Network name
- Network policy
- Proxy address
- MCP gateway state
- Number of active sessions
- Sandbox daemon version and uptime

`sbx ports <name> --json` supplies published host/guest port mappings.

The inspected host had:

- One running issue-9 castle
- One active attached session
- Two old stopped issue-9 castles

The dashboard can therefore also flag probable stale resources.

#### Castle-name metadata

The current naming convention exposes:

```text
parames-<deployment>-<invocation-or-pid>-<scope>-<unique suffix>
```

Scopes currently include:

- `planner-<iteration>`
- `issue-<issue id>`
- `merge-<root id>`

This provides a strong link between:

- Host invocation
- Phase
- Issue or root
- VM

Explicit `SANDCASTLE_DEPLOYMENT_ID` and `SANDCASTLE_INVOCATION_ID` values would make correlation more reliable than the PID fallback.

#### VM limitations

The supported JSON output does not currently provide:

- Live VM CPU usage
- Live VM memory usage
- Disk usage
- Individual session identity
- The command running in each active session
- Implementer versus reviewer identity

Allocated capacity is known from orchestration configuration—currently 4 CPUs and 8 GiB—but actual use is not exposed by `sbx inspect`.

Host shim processes expose aggregate CPU and resident memory, but correlating those processes to castle names would depend on Docker Sandboxes internals and would be less reliable than supported `sbx` APIs.

### 3. Implementer, reviewer, and merger logs

Sandcastle writes host-visible logs under:

```text
.sandcastle/logs/
```

Examples:

```text
sandcastle-issue-9-implementer-9.log
sandcastle-issue-9-reviewer-9.log
sandcastle-issue-9-merger-9.log
<planner-branch>-planner.log
```

These files are updated live and contain:

- Run start timestamp
- Current iteration and maximum iterations
- Sandbox setup progress
- Prompt shell-expansion progress
- Agent start and stop
- Assistant text
- Tool calls and abbreviated arguments
- Git synchronization and commit collection
- Completion signal outcome
- Errors and timeouts
- An immediate description of what the agent is doing

A dashboard can provide a `tail -f`-style view using file watching or polling. The inspected implementer log gave useful live descriptions of files being explored, tests being run, and frontend styles being inspected.

#### Log-derived state

The dashboard can infer statuses such as:

- Provisioning
- Installing dependencies
- Expanding the prompt
- Agent started
- Using a tool
- Committing or synchronizing
- Completed
- Failed
- Idle or stalled, based on last-write age

It can show:

- Last activity timestamp
- Log size
- Current or last tool call
- Latest assistant message
- Current iteration
- Completion marker
- Elapsed time since last output

#### Log limitations

Log filenames for issue agents are reused across invocations. New runs are appended with another `Run started` marker. Therefore:

- File existence does not mean an agent is running
- An old reviewer log does not mean the current reviewer has started
- The dashboard must identify the latest run segment
- Process, VM, and log activity must be combined

Planner filenames are more unique because their generated planner branch includes a timestamp and random suffix.

Logs may contain source code, issue bodies, tool arguments, and potentially sensitive output. Dashboard access should be local or authenticated, and raw logs should be treated as sensitive.

### 4. Agent stream available with light instrumentation

Sandcastle already supports an observability callback:

```ts
logging: {
  type: "file",
  path,
  onAgentStreamEvent(event) { /* forward event */ }
}
```

It emits live structured events:

- `text`
  - Message
  - Iteration
  - Timestamp
- `toolCall`
  - Tool name
  - Formatted arguments
  - Iteration
  - Timestamp
- `raw`
  - Raw stream line
  - Iteration
  - Timestamp

This would be a cleaner source for a future dashboard than parsing human-readable log files. It could feed an in-memory event bus, WebSocket, SSE endpoint, or local database while retaining normal logs.

Completed run results additionally provide:

- Iteration list
- Claude session ID
- Captured transcript path
- Token usage:
  - Input tokens
  - Cache-creation tokens
  - Cache-read tokens
  - Output tokens
- Completion signal
- Commits produced
- Log path

Most result information is only returned after an iteration finishes. The callback does not directly expose session IDs, although raw initialization events contain them and could be parsed.

### 5. Agent lifecycle and phase identity

The current issue pipeline is sequential:

```text
issue VM
├── implementer
└── reviewer, after implementer completes
```

The implementer and reviewer share the same castle. There are not normally two simultaneously running VM sessions for one issue.

Consequences:

- `sbx inspect` showing one active session does not identify whether it is the implementer or reviewer.
- The castle name identifies only `issue-9`.
- The active phase must be derived from the latest active log or from structured events added at orchestration boundaries.
- The reviewer log appears after implementation completes, but old reviewer logs may already exist from previous invocations.

Planner and merger castles have phase-specific names and are easier to identify.

### 6. Git information

From the host, the dashboard can obtain:

- Active worktree path
- Branch name
- Issue ID from `sandcastle/issue-<id>`
- HEAD commit
- Recent commits
- Ahead/behind state
- Clean or dirty status
- Whether branches and worktrees remain after interruption
- Branch-to-worktree mapping
- Root and dependent branch existence

This supports actions or links such as:

```text
Open worktree
Show diff
Show recent commits
Review preserved work
```

#### Isolation caveat

While an agent is running, its actual repository is inside the microVM. Changes are synchronized back to the host only at Sandcastle lifecycle boundaries. Host Git status is therefore not a reliable live view of in-progress guest edits.

Obtaining live guest Git status would require an `sbx exec` or copy operation. That is possible, but creates another sandbox session and should not be necessary for the first draft.

### 7. GitHub context

Given an issue ID or branch, the host can query:

- Issue title and state
- Labels
- Parent or root issue
- Comments
- Draft/root pull request
- Pull request state and URL
- Review state
- Branch publication state

This would let cards say, for example:

```text
#9 Adapt the frontend automatically to the system color scheme
Phase: Implementing
Branch: sandcastle/issue-9
VM: running
Last activity: 4 seconds ago
```

This requires network access and GitHub credentials, so it should be cached and should not block live process display.

Root and dependency mappings currently live in planner output and orchestration memory. Recovering them afterward would require parsing planner logs or querying GitHub again.

## Important visibility gaps

Without changing Sandcastle orchestration, the dashboard cannot reliably know:

- A stable run or invocation ID in every environment
- Exact phase transitions independent of logs
- Whether the current issue session is the implementer or reviewer
- Final process exit reason when the dashboard is not the parent
- Live guest Git changes
- Live per-VM CPU, memory, or disk use through supported `sbx` JSON
- The planner's validated issue graph except by parsing its log
- Historical run outcomes in a structured format
- Whether a disappeared process completed or crashed

The orchestration's own high-level stdout, such as `Iteration 1/1`, is written to its terminal rather than a persistent host file. A separately launched dashboard cannot safely attach to that existing terminal stream.

## Feasible first-draft dashboard

### Host runs

- Repository
- Host PID
- Start time and elapsed time
- Process status
- CPU and resident memory
- Number of running castles
- Inferred current phase
- Last activity
- Stale or no-output warning

### Session/castle cards

- Planner, issue, or merger role
- Issue or root number
- Issue title from GitHub
- Implementer or reviewer inferred from the active log
- VM name and UUID
- Running or stopped state
- Uptime
- Active session count
- Template and digest
- Published ports
- Worktree and branch
- Latest commit
- Live log tail

### Historical and stale resources

- Stopped castles
- Missing workspace warning
- Preserved worktrees
- Old branches
- Last known log result
- Cleanup instructions

## Recommendation

For the first read-only version, use:

1. `/proc` for host-run discovery and resource usage
2. `sbx ls`, `sbx inspect`, and `sbx ports` with `--json` for VM state
3. Log tailing for live work visibility
4. Git for branches and worktrees
5. GitHub only for human-friendly issue and pull-request metadata

A later iteration should add a small structured run/event registry and Sandcastle's `onAgentStreamEvent` callback. That would remove most inference and log-parsing ambiguity while leaving existing agent execution unchanged.
