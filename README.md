# Newtonite Operations

A small internal work coordination app built with React + TypeScript (Vite) and Flask. It includes a paginated, searchable work queue, team filters, item details and activity history, comments, team roles, workflow rules, and version-checked updates.

## Product assumptions

- This is an internal tool with seeded email/password accounts; there is no public signup or SSO.
- Users can belong to multiple teams with a different role in each team. Each work item belongs to one team.
- The product exposes three user types: `Member`, `Team leader`, and `Admin`. Members can view team work and collaborate within the permissions granted to them. Only the Team leader can modify task details, assignment, priority, due date, or workflow. Admin is reserved for membership administration.
- The workflow is fixed. Notifications are in-app only, and email delivery is intentionally not implemented.
- A single PostgreSQL instance is the production target. SQLite is the local default for easy evaluation.

## Run locally

### Requirements

- Python 3.10 or newer
- Node.js 20 or newer

### Backend

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

The API starts at `http://localhost:5000`. On first launch it creates a local SQLite database and sample records.

### Frontend

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## Demo users

All demo accounts use password `demo1234`.

| User | Role | Email |
| --- | --- | --- |
| Alex Morgan | Operations member | `alex@newtonite.local` |
| Sam Rivera | Operations and Engineering lead | `sam@newtonite.local` |
| Jordan Lee | Operations member; Engineering admin | `jordan@newtonite.local` |

These credentials and the development secret key are for local preview only. Replace them before deploying this app.

## Database configuration

The default is a SQLite database created by Flask-SQLAlchemy. To use PostgreSQL, install the included `psycopg` dependency and set `DATABASE_URL`, for example:

```text
postgresql+psycopg://user:password@localhost:5432/newtonite
```

Set `SECRET_KEY` to a private random value in any non-local environment.

## Automated tests

From the `backend` folder with the virtual environment activated, install the requirements and run:

```powershell
python -m pip install -r requirements.txt
python -m pytest
```

The tests use a temporary in-memory SQLite database and cover competing claims, stale updates, team-level access, role restrictions, and invalid workflow transitions.

## Important behavior

- Users only see items in teams where they have a membership.
- Members can view, create, comment, and claim work. Only Team leaders can modify task details, assignment, priority, due date, or workflow. Admins manage team membership but do not modify tasks.
- Claiming uses an atomic conditional update. Two users cannot both claim an unassigned item.
- Item edits include a version number. A stale update returns HTTP 409 with the current item so the client can refresh.
- Item changes and corresponding history entries are committed together.
- Create, claim, and versioned updates accept an `Idempotency-Key` and replay stored responses on retries.
- Required-approval items cannot be resolved until a team lead approves them; requesters cannot approve their own requests.
- Activity history has a limited endpoint with continuation support, while queue results use server-side page pagination.
- Dashboard counts and approval records are server-owned APIs/models. Notification and job tables/endpoints exist as foundations, but delivery and worker processing are not complete.
- Queue search, filters, and pagination are handled by the API.

## Current submission scope

The completed correctness slice includes team-scoped authorization, Admin membership management, atomic claiming, optimistic locking, idempotent mutations, workflow validation, approval API rules, comments, activity history, server-side filtering, and page-based pagination.

The following are intentionally partial or deferred: the approval UI, notification delivery, polling/live refresh, the asynchronous job worker, retry/backoff processing, PostgreSQL full-text search, production migrations, large-data seeding, and performance benchmarking. The project uses Flask sessions rather than JWT and does not claim a running worker or cursor-based queue pagination.

## Known limitations

- Demo login is seeded and does not include password reset, invitation, or account administration flows.
- The UI currently uses a simple side panel for item details; there are no real-time updates or notifications.
- The approval interface, notification delivery UI, and polling/live refresh are incomplete.
- Database schema creation uses `create_all`; production migrations are not configured.
- Activity history is capped to the latest 100 entries in item details.
- SQLite is suitable for local evaluation, not the anticipated concurrent production workload. Use PostgreSQL for a deployed instance.
- A job table exists, but the polling worker, `FOR UPDATE SKIP LOCKED` processing, retries, and backoff are not implemented.
- PostgreSQL full-text search, `tsvector`/GIN indexes, 50k/500k large-data seeding, and `EXPLAIN ANALYZE` benchmarking are not implemented; local search uses database text filtering.
- Idempotency records currently have no cleanup task and need a retention policy in production.
