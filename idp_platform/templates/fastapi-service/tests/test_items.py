from uuid import uuid4


def test_create_get_replace_delete(client):
    created = client.post("/api/v1/items", json={"name": "widget", "description": "a thing"})
    assert created.status_code == 201
    item = created.json()
    assert item["name"] == "widget"

    assert client.get(f"/api/v1/items/{item['id']}").json() == item

    replaced = client.put(f"/api/v1/items/{item['id']}", json={"name": "gadget"})
    assert replaced.status_code == 200
    assert replaced.json() == {"id": item["id"], "name": "gadget", "description": None}

    deleted = client.delete(f"/api/v1/items/{item['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert client.get(f"/api/v1/items/{item['id']}").status_code == 404


def test_list_paginates(client):
    for n in range(5):
        client.post("/api/v1/items", json={"name": f"item-{n}"})

    page = client.get("/api/v1/items", params={"offset": 1, "limit": 2}).json()
    assert [i["name"] for i in page] == ["item-1", "item-2"]


def test_list_rejects_out_of_range_limit(client):
    assert client.get("/api/v1/items", params={"limit": 0}).status_code == 422
    assert client.get("/api/v1/items", params={"limit": 101}).status_code == 422


def test_validation_errors(client):
    assert client.post("/api/v1/items", json={"name": ""}).status_code == 422
    assert client.post("/api/v1/items", json={}).status_code == 422
    assert client.get("/api/v1/items/not-a-uuid").status_code == 422


def test_missing_item_returns_404(client):
    missing = uuid4()
    assert client.get(f"/api/v1/items/{missing}").status_code == 404
    assert client.put(f"/api/v1/items/{missing}", json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/v1/items/{missing}").status_code == 404
