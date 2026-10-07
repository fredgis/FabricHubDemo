# MSFlix implementation contract

Read `docs/IMPLEMENTATION-PLAN.md` before changes. SAP is excluded.

This repository contains a real, deployable entertainment demonstration. Customer
identities are fictional; catalog metadata and licensed artwork are sourced.
Transactions must be persisted and events must come from those transactions.
Never substitute hardcoded KPIs, mock connections or simulated successful jobs.

All code comments are in English. Secrets and tokens belong in authentication
caches or Key Vault, never source control, logs or frontend bundles.

The Fabric target is one MSFlix workspace on F16 in Southeast Asia (Singapore).
Raw and Silver are separate schema-enabled Lakehouses; Gold is a Warehouse.
Only explicitly tagged MSFlix resources are in deployment scope.

Use installed, version-locked Rayfin documentation before writing cockpit code.
Read the cockpit's AGENTS.md and `.agents/skills/rayfin/SKILL.md`; use Rayfin docs
CLI if its MCP server is unavailable. Do not enable legacy TypeScript decorators.

Keep infrastructure, operational business logic and analytics independently
rerunnable. Do not destroy or reinitialize existing databases on rerun.
Record real deployment evidence and concrete blockers in `.state/`, not fake
successes. GPU and Ontology v2 must be qualified rather than silently substituted.
