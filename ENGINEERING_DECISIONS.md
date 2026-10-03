# Engineering decisions

## 1. React + Flask, with a small REST boundary

The frontend and API are separate processes and communicate through JSON endpoints. This is straightforward to run and easy to explain. Vite serves the development UI; Flask owns validation, access checks, and persistence.

## 2. SQLite locally, PostgreSQL by configuration

SQLite keeps the first run simple and avoids requiring a local database service. The API accepts `DATABASE_URL`, and PostgreSQL support is included for a multi-user deployment. SQLite is only the evaluation default; it is not the recommended production database for the target concurrency.

## 3. Team membership carries the role

Roles live on a user's team membership, because a person may lead one team and be a member of another. Every item read or update checks membership for that item's team on the API.

The product exposes three user types: Member, Team leader, and Admin. The authorization policy maps the legacy demo roles `member` and `lead` to Member and Team leader. A single `can(user, action, item_or_team)` function owns the resource-level checks. Only Team leader can modify task data or workflow; Admin is reserved for membership administration. An inaccessible item returns `404` so membership boundaries do not reveal its existence.

## 4. Optimistic version checks protect edits

Each item has a monotonically increasing version. A write updates only when the submitted version still matches the stored version. A conflict returns the latest item and asks the user to review current data rather than silently overwrite it.

## 5. Claiming is an atomic database operation

Claiming updates an item only while its assignee is empty and its version matches. The database decides which competing request wins. A successful change and its activity entry share one transaction.

## 6. PostgreSQL jobs table as a future async boundary

The schema includes jobs and notifications as a planned foundation, but the current slice does not yet insert outbox jobs for every mutation or run a worker. The intended design is a PostgreSQL polling worker with retries, backoff, and idempotent notification handlers. Keeping that future boundary in PostgreSQL avoids adding Redis or another operational dependency. The trade-off is that a database-backed queue will not scale like Kafka or SQS.

## 7. Keep the workflow fixed for the first version

The status graph is small and validated by the API. A configurable workflow editor would add complexity without improving the core demonstration. Notifications, polling/live updates, and the approval UI are also deferred.

## Deliberately deferred

Production authentication/SSO, JWT-based auth, migrations, email delivery, live push updates, file attachments, custom workflows, PostgreSQL full-text search, large-data benchmarking, and expanded reporting are outside this first slice. Team administration screens are implemented for Admin users. Demo credentials and the development secret are not production security settings.
