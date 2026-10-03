"""Newtonite operations API. Run with: flask --app app run --debug"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request, session
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, inspect, or_, text, update
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def now_utc():
    return datetime.now(timezone.utc)


def upgrade_local_schema():
    """Apply small additive upgrades for the local SQLite database.

    SQLAlchemy's create_all creates missing tables but does not add columns to
    tables created by an earlier version of the app.
    """
    if db.engine.dialect.name != "sqlite":
        return
    columns = {column["name"] for column in inspect(db.engine).get_columns("work_item")}
    additions = {
        "created_by": "INTEGER",
        "requires_approval": "BOOLEAN NOT NULL DEFAULT 0",
    }
    with db.engine.begin() as connection:
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE work_item ADD COLUMN {name} {definition}"))


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    memberships = db.relationship("Membership", back_populates="user", cascade="all, delete-orphan")


class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    memberships = db.relationship("Membership", back_populates="team", cascade="all, delete-orphan")


class Membership(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False, default="member")
    __table_args__ = (db.UniqueConstraint("user_id", "team_id"),)
    user = db.relationship("User", back_populates="memberships")
    team = db.relationship("Team", back_populates="memberships")


class WorkItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False, index=True)
    status = db.Column(db.String(30), nullable=False, default="Open", index=True)
    priority = db.Column(db.String(20), nullable=False, default="Normal", index=True)
    assignee_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    requires_approval = db.Column(db.Boolean, nullable=False, default=False)
    due_date = db.Column(db.Date, nullable=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_utc, index=True)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_utc)
    team = db.relationship("Team")
    assignee = db.relationship("User", foreign_keys=[assignee_id])


class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("work_item.id"), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    kind = db.Column(db.String(30), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_utc, index=True)
    actor = db.relationship("User")


class IdempotencyKey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(120), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    endpoint = db.Column(db.String(160), nullable=False)
    response = db.Column(db.JSON, nullable=False)
    status_code = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_utc)
    __table_args__ = (db.UniqueConstraint("user_id", "key"),)


class Approval(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("work_item.id"), nullable=False, index=True)
    requested_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    approver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending")
    decided_at = db.Column(db.DateTime(timezone=True), nullable=True)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("work_item.id"), nullable=True)
    message = db.Column(db.Text, nullable=False)
    job_id = db.Column(db.Integer, nullable=True)
    read_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_utc)
    __table_args__ = (db.UniqueConstraint("job_id", "user_id"),)


class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(80), nullable=False)
    payload = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")
    attempts = db.Column(db.Integer, nullable=False, default=0)
    run_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_utc)
    last_error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_utc)


TRANSITIONS = {
    "Open": {"In progress", "Blocked"},
    "In progress": {"Waiting for approval", "Blocked", "Resolved", "Open"},
    "Waiting for approval": {"In progress", "Blocked", "Resolved"},
    "Blocked": {"Open", "In progress"},
    "Resolved": set(),
}
STATUSES = set(TRANSITIONS)
PRIORITIES = {"Low", "Normal", "High", "Urgent"}


def create_app(test_config=None):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "local-development-key-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///newtonite.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if test_config:
        app.config.update(test_config)
    db.init_app(app)
    CORS(app, supports_credentials=True, origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ])

    @app.errorhandler(400)
    def bad_request(error):
        return jsonify(error="bad_request", message=str(error.description)), 400

    @app.errorhandler(404)
    def not_found(error):
        return jsonify(error="not_found", message="The requested resource was not found."), 404

    @app.errorhandler(500)
    def server_error(error):
        db.session.rollback()
        return jsonify(error="server_error", message="Something went wrong. Please retry."), 500

    def current_user():
        user_id = session.get("user_id")
        return db.session.get(User, user_id) if user_id else None

    def require_user():
        user = current_user()
        if not user:
            return None, (jsonify(error="unauthorized", message="Please sign in."), 401)
        return user, None

    def membership_for(user, team_id):
        return Membership.query.filter_by(user_id=user.id, team_id=team_id).first()

    def has_team_access(user, team_id):
        return membership_for(user, team_id) is not None

    def can(user, action, item_or_team):
        team_id = item_or_team.team_id if hasattr(item_or_team, "team_id") else item_or_team
        member = membership_for(user, team_id)
        if not member:
            return False
        role = member.role
        managers = {"manager", "lead"}
        agents = {"agent", "member", "manager", "lead", "admin"}
        if action == "view":
            return True
        if action in {"create", "comment", "claim"}:
            return role in agents
        if action in {"assign", "edit", "transition", "approve"}:
            return role in managers
        if action == "manage_members":
            return role == "admin"
        return False

    def item_json(item, include_activity=False):
        data = {
            "id": item.id, "title": item.title, "description": item.description,
            "team_id": item.team_id, "team": item.team.name,
            "status": item.status, "priority": item.priority,
            "assignee_id": item.assignee_id,
            "assignee": item.assignee.name if item.assignee else None,
            "created_by": item.created_by,
            "requires_approval": item.requires_approval,
            "due_date": item.due_date.isoformat() if item.due_date else None,
            "version": item.version,
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
        }
        if include_activity:
            entries = Activity.query.filter_by(item_id=item.id).order_by(Activity.created_at.desc(), Activity.id.desc()).limit(100).all()
            data["activity"] = [{
                "id": e.id, "kind": e.kind, "message": e.message,
                "actor": e.actor.name, "created_at": e.created_at.isoformat(),
            } for e in reversed(entries)]
        return data

    def add_activity(item, actor, kind, message):
        db.session.add(Activity(item_id=item.id, actor_id=actor.id, kind=kind, message=message))

    def idempotent_response(user, endpoint):
        key = request.headers.get("Idempotency-Key")
        if not key:
            return None
        previous = IdempotencyKey.query.filter_by(user_id=user.id, key=key).first()
        if previous:
            return jsonify(previous.response), previous.status_code
        return None

    def remember_response(user, endpoint, response_body, status_code):
        key = request.headers.get("Idempotency-Key")
        if key:
            db.session.add(IdempotencyKey(key=key, user_id=user.id,
                                         endpoint=endpoint, response=response_body,
                                         status_code=status_code))

    def serialize_activity(entry):
        return {"id": entry.id, "kind": entry.kind, "message": entry.message,
                "actor": entry.actor.name, "created_at": entry.created_at.isoformat()}

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    @app.post("/api/login")
    def login():
        body = request.get_json(silent=True) or {}
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
        user = User.query.filter(func.lower(User.email) == email).first()
        if not user or not check_password_hash(user.password_hash, password):
            return jsonify(error="invalid_credentials", message="Email or password is incorrect."), 401
        session.clear()
        session["user_id"] = user.id
        roles = [{"team_id": m.team_id, "team": m.team.name, "role": m.role} for m in user.memberships]
        return jsonify(user={"id": user.id, "name": user.name, "email": user.email, "memberships": roles})

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get("/api/me")
    def me():
        user, error = require_user()
        if error:
            return error
        roles = [{"team_id": m.team_id, "team": m.team.name, "role": m.role} for m in user.memberships]
        return jsonify(user={"id": user.id, "name": user.name, "email": user.email, "memberships": roles})

    @app.get("/api/teams")
    def teams():
        user, error = require_user()
        if error:
            return error
        return jsonify(teams=[{"id": m.team.id, "name": m.team.name, "role": m.role} for m in user.memberships])

    @app.get("/api/users")
    def users():
        user, error = require_user()
        if error:
            return error
        team_id = request.args.get("team_id", type=int)
        if not team_id or not has_team_access(user, team_id):
            return jsonify(error="forbidden", message="You do not have access to this team."), 403
        members = User.query.join(Membership).filter(Membership.team_id == team_id).order_by(User.name).all()
        return jsonify(users=[{"id": u.id, "name": u.name} for u in members])

    @app.get("/api/teams/<int:team_id>/members")
    def team_members(team_id):
        user, error = require_user()
        if error:
            return error
        if not can(user, "manage_members", team_id):
            return jsonify(error="forbidden", message="Only a team admin can manage members."), 403
        members = Membership.query.filter_by(team_id=team_id).join(User).order_by(User.name).all()
        member_ids = {member.user_id for member in members}
        available_users = User.query.filter(~User.id.in_(member_ids)).order_by(User.name).all() if member_ids else User.query.order_by(User.name).all()
        return jsonify(members=[{"user_id": member.user_id, "name": member.user.name,
                                 "email": member.user.email, "role": member.role}
                    for member in members],
                   available_users=[{"id": candidate.id, "name": candidate.name,
                          "email": candidate.email} for candidate in available_users])

    @app.post("/api/teams/<int:team_id>/members")
    def add_team_member(team_id):
        user, error = require_user()
        if error:
            return error
        if not can(user, "manage_members", team_id):
            return jsonify(error="forbidden", message="Only a team admin can manage members."), 403
        body = request.get_json(silent=True) or {}
        target_id = body.get("user_id")
        role = body.get("role", "member")
        if not isinstance(target_id, int) or role not in {"member", "lead", "admin"}:
            return jsonify(error="invalid_member", message="Choose a user and a valid role."), 400
        target = db.session.get(User, target_id)
        if not target:
            return jsonify(error="invalid_member", message="User not found."), 404
        if Membership.query.filter_by(user_id=target_id, team_id=team_id).first():
            return jsonify(error="member_exists", message="This user is already a team member."), 409
        membership = Membership(user_id=target_id, team_id=team_id, role=role)
        db.session.add(membership)
        db.session.commit()
        return jsonify(member={"user_id": target.id, "name": target.name,
                               "email": target.email, "role": role}), 201

    @app.patch("/api/teams/<int:team_id>/members/<int:user_id>")
    def update_team_member(team_id, user_id):
        user, error = require_user()
        if error:
            return error
        if not can(user, "manage_members", team_id):
            return jsonify(error="forbidden", message="Only a team admin can manage members."), 403
        membership = Membership.query.filter_by(user_id=user_id, team_id=team_id).first()
        role = (request.get_json(silent=True) or {}).get("role")
        if not membership:
            return jsonify(error="not_found", message="Team member not found."), 404
        if role not in {"member", "lead", "admin"}:
            return jsonify(error="invalid_role", message="Choose member, lead, or admin."), 400
        membership.role = role
        db.session.commit()
        return jsonify(member={"user_id": membership.user_id, "name": membership.user.name,
                               "email": membership.user.email, "role": membership.role})

    @app.delete("/api/teams/<int:team_id>/members/<int:user_id>")
    def remove_team_member(team_id, user_id):
        user, error = require_user()
        if error:
            return error
        if not can(user, "manage_members", team_id):
            return jsonify(error="forbidden", message="Only a team admin can manage members."), 403
        membership = Membership.query.filter_by(user_id=user_id, team_id=team_id).first()
        if not membership:
            return jsonify(error="not_found", message="Team member not found."), 404
        if membership.user_id == user.id:
            return jsonify(error="invalid_member", message="You cannot remove yourself from this team."), 422
        db.session.delete(membership)
        db.session.commit()
        return jsonify(ok=True)

    @app.get("/api/items")
    def list_items():
        user, error = require_user()
        if error:
            return error
        team_ids = [m.team_id for m in user.memberships]
        query = WorkItem.query.filter(WorkItem.team_id.in_(team_ids))
        text = request.args.get("q", "").strip()
        if text:
            like = f"%{text}%"
            query = query.filter(or_(WorkItem.title.ilike(like), WorkItem.description.ilike(like)))
        for arg, column in (("status", WorkItem.status), ("priority", WorkItem.priority), ("assignee_id", WorkItem.assignee_id), ("team_id", WorkItem.team_id)):
            value = request.args.get(arg)
            if value and value != "all":
                if arg.endswith("_id") or arg == "team_id":
                    try:
                        value = int(value)
                    except ValueError:
                        return jsonify(error="invalid_filter", message=f"{arg} must be a number."), 400
                query = query.filter(column == value)
        if request.args.get("mine") == "true":
            query = query.filter(WorkItem.assignee_id == user.id)
        page = max(1, request.args.get("page", 1, type=int))
        per_page = min(50, max(1, request.args.get("per_page", 20, type=int)))
        pagination = query.order_by(WorkItem.updated_at.desc(), WorkItem.id.desc()).paginate(page=page, per_page=per_page, error_out=False)
        return jsonify(items=[item_json(i) for i in pagination.items], page=page,
                       per_page=per_page, total=pagination.total, pages=pagination.pages)

    @app.post("/api/items")
    def create_item():
        user, error = require_user()
        if error:
            return error
        previous = idempotent_response(user, request.path)
        if previous:
            return previous
        body = request.get_json(silent=True) or {}
        title = str(body.get("title", "")).strip()
        team_id = body.get("team_id")
        if not title or len(title) > 200:
            return jsonify(error="invalid_title", message="A title of 1–200 characters is required."), 400
        if not isinstance(team_id, int) or not can(user, "create", team_id):
            return jsonify(error="forbidden", message="Choose a team you belong to."), 403
        priority = body.get("priority", "Normal")
        if priority not in PRIORITIES:
            return jsonify(error="invalid_priority", message="Choose a valid priority."), 400
        item = WorkItem(title=title, description=str(body.get("description", "")).strip(),
                team_id=team_id, priority=priority, status="Open",
                created_by=user.id, requires_approval=bool(body.get("requires_approval", False)))
        if body.get("due_date"):
            try:
                from datetime import date
                item.due_date = date.fromisoformat(body["due_date"])
            except (ValueError, TypeError):
                return jsonify(error="invalid_due_date", message="Use YYYY-MM-DD for the due date."), 400
        db.session.add(item)
        db.session.flush()
        add_activity(item, user, "created", f"Created “{item.title}”.")
        response_body = {"item": item_json(item, True)}
        remember_response(user, request.path, response_body, 201)
        db.session.commit()
        return jsonify(response_body), 201

    def get_accessible_item(user, item_id):
        item = db.session.get(WorkItem, item_id)
        if not item:
            return None, (jsonify(error="not_found", message="Work item not found."), 404)
        if not can(user, "view", item):
            return None, (jsonify(error="not_found", message="Work item not found."), 404)
        return item, None

    @app.get("/api/items/<int:item_id>")
    def get_item(item_id):
        user, error = require_user()
        if error:
            return error
        item, error = get_accessible_item(user, item_id)
        if error:
            return error
        return jsonify(item=item_json(item, True))

    @app.patch("/api/items/<int:item_id>")
    def update_item(item_id):
        user, error = require_user()
        if error:
            return error
        item, error = get_accessible_item(user, item_id)
        if error:
            return error
        previous = idempotent_response(user, request.path)
        if previous:
            return previous
        body = request.get_json(silent=True) or {}
        expected = body.get("version")
        if not isinstance(expected, int):
            return jsonify(error="version_required", message="Refresh the item before saving."), 428
        lead = can(user, "edit", item)
        fields = set(body) - {"version"}
        if not fields:
            return jsonify(item=item_json(item, True))
        if not lead:
            return jsonify(error="forbidden", message="You cannot make that change to this item."), 403
        if "status" in body:
            new_status = body["status"]
            if new_status not in STATUSES or new_status not in TRANSITIONS[item.status]:
                return jsonify(error="invalid_transition", message=f"Cannot move an item from {item.status} to {new_status}."), 409
            if new_status == "Resolved" and item.requires_approval and not Approval.query.filter_by(item_id=item.id, status="approved").first():
                return jsonify(error="approval_required", message="This item needs an approved request before it can be resolved."), 422
        if "priority" in body and body["priority"] not in PRIORITIES:
            return jsonify(error="invalid_priority", message="Choose a valid priority."), 400
        if "assignee_id" in body and body["assignee_id"] is not None:
            target = db.session.get(User, body["assignee_id"])
            if not target or not has_team_access(target, item.team_id):
                return jsonify(error="invalid_assignee", message="The assignee must belong to this team."), 400
        changes = []
        new_values = {}
        for field in ("title", "description", "priority", "status", "assignee_id", "due_date"):
            if field not in body:
                continue
            value = body[field]
            if field == "title":
                value = str(value).strip()
                if not value or len(value) > 200:
                    return jsonify(error="invalid_title", message="A title of 1–200 characters is required."), 400
            if field == "description":
                value = str(value).strip()
            if field == "due_date" and value:
                try:
                    from datetime import date
                    value = date.fromisoformat(value)
                except (ValueError, TypeError):
                    return jsonify(error="invalid_due_date", message="Use YYYY-MM-DD for the due date."), 400
            old = getattr(item, field)
            if field == "due_date" and old:
                old = old.isoformat()
            if old != value:
                changes.append((field, old, value))
                new_values[field] = value
        if not changes:
            return jsonify(item=item_json(item, True))
        statement = update(WorkItem).where(WorkItem.id == item.id, WorkItem.version == expected).values(
            **new_values, version=WorkItem.version + 1, updated_at=now_utc())
        result = db.session.execute(statement)
        if result.rowcount != 1:
            db.session.rollback()
            current = db.session.get(WorkItem, item_id)
            return jsonify(error="version_conflict", message="Someone changed this item. Reload it and review their changes.", item=item_json(current, True)), 409
        for field, old, new in changes:
            if field == "assignee_id":
                old_name = db.session.get(User, old).name if old else "Unassigned"
                new_name = db.session.get(User, new).name if new else "Unassigned"
                label, before, after = "Owner", old_name, new_name
            elif field == "due_date":
                label, before, after = "Due date", str(old or "None"), str(new or "None")
            else:
                label, before, after = field.replace("_", " ").title(), str(old), str(new)
            add_activity(item, user, "changed", f"{label} changed from {before} to {after}.")
        response_body = {"item": item_json(db.session.get(WorkItem, item_id), True)}
        remember_response(user, request.path, response_body, 200)
        db.session.commit()
        db.session.expire_all()
        return jsonify(response_body)

    @app.post("/api/items/<int:item_id>/claim")
    def claim_item(item_id):
        user, error = require_user()
        if error:
            return error
        item, error = get_accessible_item(user, item_id)
        if error:
            return error
        if not can(user, "claim", item):
            return jsonify(error="forbidden", message="You cannot claim work in this team."), 403
        previous = idempotent_response(user, request.path)
        if previous:
            return previous
        expected = (request.get_json(silent=True) or {}).get("version")
        if not isinstance(expected, int):
            return jsonify(error="version_required", message="Refresh the item before claiming it."), 428
        result = db.session.execute(update(WorkItem).where(
            WorkItem.id == item.id, WorkItem.assignee_id.is_(None), WorkItem.version == expected
        ).values(assignee_id=user.id, status="In progress", version=WorkItem.version + 1, updated_at=now_utc()))
        if result.rowcount != 1:
            db.session.rollback()
            current = db.session.get(WorkItem, item_id)
            return jsonify(error="claim_conflict", message="This item was claimed or changed by someone else.", item=item_json(current, True)), 409
        add_activity(item, user, "assigned", f"{user.name} claimed this item.")
        response_body = {"item": item_json(db.session.get(WorkItem, item_id), True)}
        remember_response(user, request.path, response_body, 200)
        db.session.commit()
        db.session.expire_all()
        return jsonify(response_body)

    @app.post("/api/items/<int:item_id>/comments")
    def comment_item(item_id):
        user, error = require_user()
        if error:
            return error
        item, error = get_accessible_item(user, item_id)
        if error:
            return error
        if not can(user, "comment", item):
            return jsonify(error="forbidden", message="You cannot comment on work in this team."), 403
        message = str((request.get_json(silent=True) or {}).get("message", "")).strip()
        if not message or len(message) > 4000:
            return jsonify(error="invalid_comment", message="Write a comment of 1–4000 characters."), 400
        add_activity(item, user, "comment", message)
        db.session.commit()
        return jsonify(item=item_json(db.session.get(WorkItem, item_id), True)), 201

    @app.get("/api/items/<int:item_id>/activity")
    def item_activity(item_id):
        user, error = require_user()
        if error:
            return error
        item, error = get_accessible_item(user, item_id)
        if error:
            return error
        limit = min(100, max(1, request.args.get("limit", 30, type=int)))
        query = Activity.query.filter_by(item_id=item.id)
        before = request.args.get("before", type=int)
        if before:
            query = query.filter(Activity.id < before)
        entries = query.order_by(Activity.id.desc()).limit(limit + 1).all()
        has_more = len(entries) > limit
        entries = entries[:limit]
        return jsonify(activity=[serialize_activity(entry) for entry in reversed(entries)],
                       next_cursor=entries[-1].id if has_more else None)

    @app.post("/api/items/<int:item_id>/approvals")
    def request_approval(item_id):
        user, error = require_user()
        if error:
            return error
        item, error = get_accessible_item(user, item_id)
        if error:
            return error
        if not item.requires_approval:
            return jsonify(error="approval_not_required", message="This item does not require approval."), 422
        approval = Approval(item_id=item.id, requested_by=user.id)
        db.session.add(approval)
        add_activity(item, user, "approval_requested", f"{user.name} requested approval.")
        db.session.commit()
        return jsonify(approval={"id": approval.id, "status": approval.status}), 201

    @app.post("/api/approvals/<int:approval_id>/decision")
    def decide_approval(approval_id):
        user, error = require_user()
        if error:
            return error
        approval = db.session.get(Approval, approval_id)
        if not approval:
            return jsonify(error="not_found", message="Approval not found."), 404
        item, error = get_accessible_item(user, approval.item_id)
        if error:
            return error
        if not can(user, "approve", item) or approval.requested_by == user.id:
            return jsonify(error="forbidden", message="You cannot decide this approval."), 403
        decision = (request.get_json(silent=True) or {}).get("status")
        if decision not in {"approved", "rejected"} or approval.status != "pending":
            return jsonify(error="invalid_decision", message="Choose approved or rejected for a pending approval."), 422
        approval.status = decision
        approval.approver_id = user.id
        approval.decided_at = now_utc()
        add_activity(item, user, "approval_decided", f"{user.name} {decision} approval.")
        db.session.commit()
        return jsonify(approval={"id": approval.id, "status": approval.status}), 200

    @app.get("/api/notifications")
    def notifications():
        user, error = require_user()
        if error:
            return error
        entries = Notification.query.filter_by(user_id=user.id).order_by(Notification.created_at.desc()).limit(50).all()
        return jsonify(notifications=[{"id": n.id, "item_id": n.item_id, "message": n.message,
                                       "read_at": n.read_at.isoformat() if n.read_at else None,
                                       "created_at": n.created_at.isoformat()} for n in entries])

    @app.get("/api/dashboard")
    def dashboard():
        user, error = require_user()
        if error:
            return error
        team_ids = [m.team_id for m in user.memberships]
        base = WorkItem.query.filter(WorkItem.team_id.in_(team_ids))
        return jsonify(counts={
            "my_open": base.filter(WorkItem.assignee_id == user.id, WorkItem.status != "Resolved").count(),
            "unassigned": base.filter(WorkItem.assignee_id.is_(None), WorkItem.status != "Resolved").count(),
            "urgent": base.filter(WorkItem.priority == "Urgent", WorkItem.status != "Resolved").count(),
            "overdue": base.filter(WorkItem.due_date < now_utc().date(), WorkItem.status != "Resolved").count(),
            "awaiting_my_approval": Approval.query.filter_by(approver_id=user.id, status="pending").count(),
        })

    with app.app_context():
        db.create_all()
        upgrade_local_schema()
        seed_demo_data()
    return app


def seed_demo_data():
    if User.query.first():
        return
    ops = Team(name="Operations")
    eng = Team(name="Engineering")
    users = [
        User(name="Alex Morgan", email="alex@newtonite.local", password_hash=generate_password_hash("demo1234")),
        User(name="Sam Rivera", email="sam@newtonite.local", password_hash=generate_password_hash("demo1234")),
        User(name="Jordan Lee", email="jordan@newtonite.local", password_hash=generate_password_hash("demo1234")),
    ]
    db.session.add_all([ops, eng, *users])
    db.session.flush()
    db.session.add_all([
        Membership(user_id=users[0].id, team_id=ops.id, role="member"),
        Membership(user_id=users[1].id, team_id=ops.id, role="lead"),
        Membership(user_id=users[1].id, team_id=eng.id, role="lead"),
        Membership(user_id=users[2].id, team_id=ops.id, role="member"),
        Membership(user_id=users[2].id, team_id=eng.id, role="admin"),
    ])
    db.session.commit()


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
