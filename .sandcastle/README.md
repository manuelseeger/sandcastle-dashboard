# Sandcastle microVM operations

Sandcastle runs every phase—planning, implementation, review, and merging—in a Docker Sandboxes microVM. Every open issue labeled `sandcastle` is processed in this runtime.

The default local template is `parames-sbx:dev`, built from `Dockerfile.sbx`. The defaults allocate 4 CPUs, 8 GiB, and a 30-minute lifecycle timeout; override them with the `SANDCASTLE_SBX_*` variables in `.env.example`. Set deployment and invocation IDs in CI so castle names are ownership-scoped. Sandcastle resolves the GitHub repository from the host checkout and passes it to guests as `GH_REPO`; set `SANDCASTLE_GH_REPO=owner/repository` when the host checkout has no usable GitHub remote.

Each castle receives a one-way snapshot of this checkout's `.claude/skills` directory at `/home/agent/.claude/skills`, when it exists. The global Docker Sandboxes skill store remains disabled, so skills are not shared between castles or mounted from the host. This directory is an approved non-secret agent input only: never place credentials, `.env` files, or host-specific sensitive configuration in it.

Before scheduling work, run on a supported nested-virtualization host:

```sh
sbx version
sbx diagnose
sbx template ls
```

Each phase gets an isolated castle; implementation and review for one issue share a single castle. No ports are published by default. Inspect only named project castles with `sbx ls`; remove a known stale owned castle with `sbx rm --force <exact-name>`. Never bulk-delete unrecognised names.

Build templates from `Dockerfile.sbx` in a trusted pipeline. Templates and diagnostics must not contain repository source or secrets.
