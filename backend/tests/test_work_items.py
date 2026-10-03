import pytest

from app import Membership, Team, User, WorkItem, create_app, db


@pytest.fixture
def app():
    application = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-only-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
    })
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def sign_in(client, email):
    response = client.post("/api/login", json={"email": email, "password": "demo1234"})
    assert response.status_code == 200
    return response.get_json()["user"]


def team_id(app, name="Operations"):
    with app.app_context():
        return Team.query.filter_by(name=name).one().id


def create_item(client, app, title="Investigate delayed settlement", team="Operations"):
    return client.post("/api/items", json={
        "title": title,
        "description": "Customer reports a delayed settlement.",
        "team_id": team_id(app, team),
        "priority": "High",
    })


def test_competing_claims_have_one_winner_and_one_activity(app):
    alex = app.test_client()
    jordan = app.test_client()
    alex_user = sign_in(alex, "alex@newtonite.local")
    sign_in(jordan, "jordan@newtonite.local")
    created = create_item(alex, app)
    assert created.status_code == 201
    item = created.get_json()["item"]

    first = alex.post(f"/api/items/{item['id']}/claim", json={"version": item["version"]})
    second = jordan.post(f"/api/items/{item['id']}/claim", json={"version": item["version"]})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.get_json()["error"] == "claim_conflict"
    latest = alex.get(f"/api/items/{item['id']}").get_json()["item"]
    assert latest["assignee_id"] == alex_user["id"]
    assert len([event for event in latest["activity"] if event["kind"] == "assigned"]) == 1


def test_stale_item_version_is_rejected_with_current_item(app):
    client = app.test_client()
    sign_in(client, "sam@newtonite.local")
    created = create_item(client, app)
    item = created.get_json()["item"]

    first = client.patch(f"/api/items/{item['id']}", json={
        "version": item["version"], "priority": "Urgent",
    })
    stale = client.patch(f"/api/items/{item['id']}", json={
        "version": item["version"], "status": "In progress",
    })

    assert first.status_code == 200
    assert stale.status_code == 409
    conflict = stale.get_json()
    assert conflict["error"] == "version_conflict"
    assert conflict["item"]["priority"] == "Urgent"
    assert conflict["item"]["status"] == "Open"


def test_member_cannot_change_workflow_status(app):
    lead = app.test_client()
    member = app.test_client()
    sign_in(lead, "sam@newtonite.local")
    sign_in(member, "alex@newtonite.local")
    created = create_item(lead, app)
    item = created.get_json()["item"]

    response = member.patch(f"/api/items/{item['id']}", json={
        "version": item["version"], "status": "In progress",
    })

    assert response.status_code == 403
    assert response.get_json()["error"] == "forbidden"


def test_viewer_cannot_create_claim_or_comment(app):
    client = app.test_client()
    sign_in(client, "alex@newtonite.local")
    with app.app_context():
        alex = User.query.filter_by(email="alex@newtonite.local").one()
        operations = Team.query.filter_by(name="Operations").one()
        Membership.query.filter_by(user_id=alex.id, team_id=operations.id).update({"role": "viewer"})
        db.session.commit()

    created = client.post("/api/items", json={"title": "Viewer request", "team_id": team_id(app)})
    assert created.status_code == 403

    with app.app_context():
        lead = User.query.filter_by(email="sam@newtonite.local").one()
        item = WorkItem(title="Viewer target", team_id=team_id(app), created_by=lead.id)
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    assert client.post(f"/api/items/{item_id}/claim", json={"version": 1}).status_code == 403
    assert client.post(f"/api/items/{item_id}/comments", json={"message": "No access"}).status_code == 403


def test_member_cannot_edit_item_details(app):
    lead = app.test_client()
    member = app.test_client()
    sign_in(lead, "sam@newtonite.local")
    member_user = sign_in(member, "alex@newtonite.local")
    created = create_item(lead, app)
    item = created.get_json()["item"]
    lead.patch(f"/api/items/{item['id']}", json={
        "version": item["version"], "assignee_id": member_user["id"],
    })
    assigned = lead.get(f"/api/items/{item['id']}").get_json()["item"]

    response = member.patch(f"/api/items/{item['id']}", json={
        "version": assigned["version"], "priority": "Urgent", "due_date": "2030-01-01",
    })

    assert response.status_code == 403
    assert response.get_json()["error"] == "forbidden"


def test_admin_cannot_modify_tasks(app):
    lead = app.test_client()
    admin = app.test_client()
    sign_in(lead, "sam@newtonite.local")
    sign_in(admin, "jordan@newtonite.local")
    created = create_item(lead, app, team="Engineering")
    item = created.get_json()["item"]

    response = admin.patch(f"/api/items/{item['id']}", json={
        "version": item["version"], "priority": "Urgent",
    })

    assert response.status_code == 403
    assert response.get_json()["error"] == "forbidden"


def test_admin_can_manage_team_members_but_lead_cannot(app):
    admin = app.test_client()
    lead = app.test_client()
    admin_user = sign_in(admin, "jordan@newtonite.local")
    sign_in(lead, "sam@newtonite.local")
    with app.app_context():
        alex = User.query.filter_by(email="alex@newtonite.local").one()
        engineering = Team.query.filter_by(name="Engineering").one()
        alex_id = alex.id
        engineering_id = engineering.id

    denied = lead.get(f"/api/teams/{engineering_id}/members")
    assert denied.status_code == 403

    members = admin.get(f"/api/teams/{engineering_id}/members")
    assert members.status_code == 200
    assert all(member["user_id"] != alex_id for member in members.get_json()["members"])

    added = admin.post(f"/api/teams/{engineering_id}/members", json={
        "user_id": alex_id, "role": "member",
    })
    assert added.status_code == 201
    assert added.get_json()["member"]["role"] == "member"

    changed = admin.patch(f"/api/teams/{engineering_id}/members/{alex_id}", json={"role": "lead"})
    assert changed.status_code == 200
    assert changed.get_json()["member"]["role"] == "lead"

    removed = admin.delete(f"/api/teams/{engineering_id}/members/{alex_id}")
    assert removed.status_code == 200


def test_invalid_workflow_transition_is_rejected(app):
    client = app.test_client()
    sign_in(client, "sam@newtonite.local")
    created = create_item(client, app)
    item = created.get_json()["item"]

    response = client.patch(f"/api/items/{item['id']}", json={
        "version": item["version"], "status": "Resolved",
    })

    assert response.status_code == 409
    assert response.get_json()["error"] == "invalid_transition"


def test_user_cannot_read_an_item_from_another_team(app):
    lead = app.test_client()
    member = app.test_client()
    sign_in(lead, "sam@newtonite.local")
    sign_in(member, "alex@newtonite.local")
    created = create_item(lead, app, title="Engineering incident", team="Engineering")
    item_id = created.get_json()["item"]["id"]

    response = member.get(f"/api/items/{item_id}")

    assert response.status_code == 404
    assert response.get_json()["error"] == "not_found"


def test_replaying_create_idempotency_key_returns_one_item(app):
    client = app.test_client()
    sign_in(client, "alex@newtonite.local")
    payload = {"title": "Retry-safe request", "team_id": team_id(app), "priority": "Normal"}
    headers = {"Idempotency-Key": "create-retry-1"}

    first = client.post("/api/items", json=payload, headers=headers)
    second = client.post("/api/items", json=payload, headers=headers)

    assert first.status_code == second.status_code == 201
    assert first.get_json() == second.get_json()
    with app.app_context():
        from app import WorkItem
        assert WorkItem.query.filter_by(title="Retry-safe request").count() == 1


def test_approval_required_item_cannot_resolve_without_approval(app):
    client = app.test_client()
    sign_in(client, "sam@newtonite.local")
    created = client.post("/api/items", json={
        "title": "Approval gate", "team_id": team_id(app), "requires_approval": True,
    })
    item = created.get_json()["item"]
    client.patch(f"/api/items/{item['id']}", json={"version": item["version"], "status": "In progress"})
    response = client.patch(f"/api/items/{item['id']}", json={"version": item["version"] + 1, "status": "Resolved"})

    assert response.status_code == 422
    assert response.get_json()["error"] == "approval_required"
