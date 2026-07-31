# Sandcastle Dashboard

The Sandcastle Dashboard presents host-visible activity and resources for Sandcastle orchestration runs across repositories.

## Language

**Host Run**:
One invocation of Sandcastle orchestration discovered live and retained for the dashboard session after its process ends with an unknown outcome.

**Run Repository**:
The Git repository associated with a **Host Run** through that run's working directory.

**Castle**:
A Docker Sandbox used by a **Host Run** for a planner, issue, or merger phase.

**Stopped Castle**:
A retained **Castle** whose virtual machine is not currently running, whether intentionally preserved or left over.

## Relationships

- A **Host Run** belongs to one **Run Repository**
- A **Host Run** can have zero or more **Castles**
- A **Run Repository** can have one or more simultaneous **Host Runs**
- A **Stopped Castle** can exist without a currently discoverable **Host Run**
