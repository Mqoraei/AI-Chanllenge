# Cluster Group Client

A small Python client for creating and deleting groups across multiple cluster nodes.

The client keeps all nodes consistent by checking their state before any operation and rolling back successful changes if a later node fails.

---

## Installation
```bash
pip install -r requirements.txt
```

---

## Usage

### Create a group

```python
from cluster_client import ClusterClient

client = ClusterClient(
hosts=[
"node1.example.com",
"node2.example.com",
"node3.example.com",
]
)

try:
result = client.create_group("group-123")
print(result)
finally:
client.close()
```

### Delete a group

```python
result = client.delete_group("group-123")
```

---

## API

The client uses the following endpoints on every cluster node:

| Operation    | Method   | Endpoint              | Success      |
|--------------|----------|-----------------------|--------------|
| Get group    | `GET`    | `/v1/group/{groupId}` | 200 OK       |
| Create group | `POST`   | `/v1/group/`          | 201 Created  |
| Delete group | `DELETE` | `/v1/group/`          | 200 OK       |

### `GET /v1/group/{groupId}`

Used to check the current state of a group.

- **200 OK** — the group exists on the node.
- **404 Not Found** — the group does not exist on the node.
- Any othet Found** — the group does not exist on the node.
- Any other status code means the client could not reliably determine the group state.

### `POST /v1/group/`

Used to creatson
{
"groupId": "group-123"
}


- **201 Created** — the group was created successfully.
- **400 Bad Request** — the server rejected the request (e.g. the group already exists).
  Treated as a non-retryable failure.
- **500 Internal Server Error** — result may be ambiguous. The client performs a `GET`
  to check whether the group exists before deciding whether the `POST` can be retried.
- Any other status code is treated as an unexpected failure.

### `DELETE /v1/group/`

Used to delete a group.

Request body:

```json
{
    "groupId": "group-123"
}
```
200 OK — the group was deleted successfully.
404 Not Found — the group is already absent. Treated as a successful no-op.
500 Internal Server Error — result may be ambiguous. The client performs a GETto determine the current state before deciding whether the DELETE can be retried.
Any other status code is treated as an unexpected failure.

---

## Behavior

- Before creating or deleting a group, the client checks every node.
- If any node cannot be checked, no changes are made.
- If an operation fails after changing some nodes, the client rolls back only the changes known to have been made by that operation.
- Temporary failures are retried; after a timeout or server error, the client checks the resource state before retrying.

---

## Errors

**`ClusterOperationError`** — raised when a cluster operation fails.

**`CheckError`** — raised when the client cannot determine the state of a node before starting an operation.

Both errors include detailed information about the affected nodes.

---

## Testing


Using pytest.

Tests use `httpx.MockTransport` — no real cluster required.

---

## Assumptions

- All cluster nodes expose the same REST API.
- The caller provides the list of cluster nodes.
- `groupId` identifies the group being managed.
- The same `groupId` is not changed by another operation concurrently.
- Operations are performed sequentially, not concurrently.
- Every node can be checked with `GET` before a mutation starts.
- If the state of any node is unknown before the operation starts, no mutation is performed.
- For **create**: the expected initial state is that the group is absent on all nodes. If it already exists on any node, create is rejected and no node is changed.
- For **delete**: a node already missing the group is considered to be in the desired state.
- A successful create is identified by HTTP `201`; a successful delete by HTTP `200`.
- `GET 200` means the group exists; `GET 404` means it does not.
- `DELETE 404` is treated as a successful no-op.
- A mutation is considered owned by this operation only when the expected success response was received.
- If a timeout, connection error, or server error makes the outcome ambiguous, the mutation is treated as `unknown`.
- An `unknown` mutation is **not** automatically rolled back.
- Rollback covers only changes known to have been made by the current operation and is best-effort — it can fail.
- The API provides no distributed transactions or idempotency keys, so true atomicity cannot be guaranteed when a node remains in an unknown state.
