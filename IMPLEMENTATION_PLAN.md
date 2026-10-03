# Newtonite Operations App — Implementation Plan

## Selected stack

- Frontend: React + TypeScript + Vite.
- Backend: Flask REST API with Flask-SQLAlchemy.
- Local database: SQLite for a no-infrastructure first run; configure `DATABASE_URL` for PostgreSQL when needed.
- Local development runs as two services: Vite on port 5173 and Flask on port 5000.

## Product goal

Build a small internal app where a team can see operational work, identify its owner and next step, and understand the item's history. The first version prioritizes a reliable create → find → assign → update → review-history flow.

## First-version behavior

### Work queue

- Show work items in pages; do not load the full dataset into the browser.
- Search titles and descriptions; filter by team, status, priority, and assignee.
- Provide an “Assigned to me” view.
- Make urgent, overdue, and unassigned items visible at a glance.

### Work item

- Fields: title, description, team, status, priority, assignee (optional), optional due date, created/updated timestamps, and version.
- Statuses: Open, In progress, Waiting for approval, Blocked, Resolved.
- Detail view shows current information and a time-ordered activity history.
- Comments, assignment changes, priority changes, and status changes create history entries.

### Roles and access

- Member: view items in their teams, create items, comment, and claim unassigned work. Members cannot modify task details.
- Team leader: assign work, edit task details, change priority/due date, and move work through the workflow.
- Admin: manage team membership; Admin does not modify task details.
- Enforce role and team access in server/API operations, not just in the UI.

## Data records

- User
- Team
- TeamMembership (user, team, role)
- WorkItem (fields above)
- Activity (item, actor, type, details/comment, timestamp)

Write an item's change and its corresponding activity record as one transaction so the current state and history remain consistent.

## Correctness rules

1. Claiming succeeds only while the item is unassigned. A competing claim receives a conflict response and the current owner.
2. Updates carry the version the user last saw. A stale version is rejected with a conflict response so the UI can refresh instead of overwriting newer work.
3. Status transitions are validated on the server. Retried actions are safe and do not create duplicate history or invalid state changes.
4. Every operation checks both the user's role and their access to the item's team.

## Initial screens

1. Work queue with pagination, search, filters, attention indicators, and “Assigned to me”.
2. Create-item form.
3. Item detail with editable fields, role-appropriate actions, comments, and activity history.

## Build sequence

1. Choose the stack and establish the project structure.
2. Create the schema and a small set of development users/teams.
3. Implement server-side authorization and item APIs.
4. Build the queue, create form, and item detail flow.
5. Add activity history and the concurrency/workflow safeguards.
6. Cover high-risk behaviors with automated tests.
7. Document setup, engineering decisions, and known limitations.

## Initial scope boundaries

Keep workflows fixed and small. Notification delivery, polling/live collaboration, configurable workflows, full-text search, large-data benchmarking, and management analytics are later work unless the core flow is already complete.

## Current implementation status

Implemented and tested: team-scoped roles, Admin membership management, work-item CRUD, atomic claiming, optimistic locking, idempotency keys, workflow validation, approval API rules, comments, activity history, server-side filtering, and page-based pagination.

Partial or deferred: the approval UI, notification delivery, polling/live refresh, the job worker, retry/backoff processing, PostgreSQL full-text search, production migrations, large-data seeding, and performance benchmarking.

## Decisions to record in ENGINEERING_DECISIONS.md

Explain the chosen stack, role model, workflow rules, stale-update and competing-claim handling, and what was intentionally deferred.
