import httpx
import pytest

from cluster_client import CheckError
from cluster_client import ClusterClient
from cluster_client import ClusterOperationError
from cluster_client import GroupState


def create_client(handler):
    """
    Create a ClusterClient that uses a fake HTTP server.

    No real network connection is used in these tests.
    """

    transport = httpx.MockTransport(handler)

    http_client = httpx.Client(
        transport=transport
    )

    client = ClusterClient(
        hosts=[
            "node1.example.com",
            "node2.example.com",
        ],
        http_client=http_client,
    )

    return client


# GET tests
def test_get_group_returns_present_when_server_returns_200():

    def handler(request):
        return httpx.Response(
            200,
            json={
                "groupId": "group-123"
            },
        )

    client = create_client(handler)

    result = client.nodes[0].get_group("group-123")

    assert result["state"] == "present"
    assert result["status_code"] == 200
    assert result["reason"] == "Group exists on this node."

    client.close()


def test_get_group_state_is_a_group_state_enum_value():

    def handler(request):
        return httpx.Response(200, json={"groupId": "group-123"})

    client = create_client(handler)

    result = client.nodes[0].get_group("group-123")

    # GroupState is a str Enum, so it should still equal the plain string
    assert result["state"] == GroupState.PRESENT
    assert result["state"] == "present"

    client.close()


def test_get_group_returns_absent_when_server_returns_404():

    def handler(request):
        return httpx.Response(404)

    client = create_client(handler)

    result = client.nodes[0].get_group("group-123")

    assert result["state"] == "absent"
    assert result["status_code"] == 404

    client.close()



# CREATE tests

def test_create_group_returns_created_when_server_returns_201():

    def handler(request):
        return httpx.Response(201)

    client = create_client(handler)

    result = client.nodes[0].create_group("group-123")

    assert result["state"] == "created"
    assert result["changed"] is True
    assert result["status_code"] == 201

    client.close()


def test_create_group_returns_failed_when_server_returns_400():

    def handler(request):
        return httpx.Response(400)

    client = create_client(handler)

    result = client.nodes[0].create_group("group-123")

    assert result["state"] == "failed"
    assert result["changed"] is False
    assert result["status_code"] == 400

    client.close()



# DELETE tests

# Retry / backoff tests

def test_get_group_retries_on_connection_error_then_succeeds():

    attempt_count = 0

    def handler(request):
        nonlocal attempt_count
        attempt_count += 1

        if attempt_count < 2:
            raise httpx.ConnectError("Connection failed")

        return httpx.Response(200, json={"groupId": "group-123"})

    client = create_client(handler)
    # shrink the backoff so the test does not actually wait long
    client.nodes[0].backoff_seconds = 0.01

    result = client.nodes[0].get_group("group-123")

    assert result["state"] == "present"
    assert attempt_count == 2

    client.close()


def test_get_group_gives_up_after_retries_are_exhausted():

    attempt_count = 0

    def handler(request):
        nonlocal attempt_count
        attempt_count += 1
        raise httpx.ConnectError("Connection failed")

    client = create_client(handler)
    client.nodes[0].retries = 2
    client.nodes[0].backoff_seconds = 0.01

    result = client.nodes[0].get_group("group-123")

    assert result["state"] == "unknown"
    # retries=2 means 1 first try + 2 retries = 3 attempts total
    assert attempt_count == 3

    client.close()
def test_delete_group_returns_deleted_when_server_returns_200():

    def handler(request):
        return httpx.Response(200)

    client = create_client(handler)

    result = client.nodes[0].delete_group("group-123")

    assert result["state"] == "deleted"
    assert result["changed"] is True
    assert result["status_code"] == 200

    client.close()


def test_delete_group_returns_success_noop_when_server_returns_404():

    def handler(request):
        return httpx.Response(404)

    client = create_client(handler)

    result = client.nodes[0].delete_group("group-123")

    assert result["state"] == "deleted"
    assert result["changed"] is False
    assert result["status_code"] == 404

    client.close()



# Cluster CREATE

def test_create_group_on_all_nodes():

    def handler(request):

        if request.method == "GET":
            return httpx.Response(404)

        if request.method == "POST":
            return httpx.Response(201)

        return httpx.Response(500)

    client = create_client(handler)

    result = client.create_group("group-123")

    assert result["success"] is True
    assert result["operation"] == "create"
    assert len(result["nodes"]) == 2

    client.close()



# Cluster DELETE


def test_delete_group_on_all_nodes():

    def handler(request):

        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "groupId": "group-123"
                },
            )

        if request.method == "DELETE":
            return httpx.Response(200)

        return httpx.Response(500)

    client = create_client(handler)

    result = client.delete_group("group-123")

    assert result["success"] is True
    assert result["operation"] == "delete"
    assert len(result["nodes"]) == 2

    client.close()



# Check before operation

def test_create_fails_before_changes_if_group_already_exists():

    post_count = 0

    def handler(request):
        nonlocal post_count

        if request.method == "GET":

            if "node1.example.com" in str(request.url):
                return httpx.Response(404)

            if "node2.example.com" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "groupId": "group-123"
                    },
                )

        if request.method == "POST":
            post_count += 1
            return httpx.Response(201)

        return httpx.Response(500)

    client = create_client(handler)

    with pytest.raises(ClusterOperationError):
        client.create_group("group-123")

    assert post_count == 0

    client.close()


def test_check_before_operation_fails_when_node_state_is_unknown():

    post_count = 0

    def handler(request):
        nonlocal post_count

        if request.method == "GET":

            if "node1.example.com" in str(request.url):
                return httpx.Response(404)

            if "node2.example.com" in str(request.url):
                raise httpx.ConnectError(
                    "Connection failed"
                )

        if request.method == "POST":
            post_count += 1
            return httpx.Response(201)

        return httpx.Response(500)

    client = create_client(handler)

    with pytest.raises(CheckError):
        client.create_group("group-123")

    assert post_count == 0

    client.close()


# CREATE rollback
# ---------------------------------------------------------
def test_create_rolls_back_previous_nodes_when_later_node_fails():

    post_count = 0
    delete_count = 0

    def handler(request):
        nonlocal post_count
        nonlocal delete_count

        if request.method == "GET":
            return httpx.Response(404)

        if request.method == "POST":

            post_count += 1

            if post_count == 1:
                return httpx.Response(201)

            return httpx.Response(400)

        if request.method == "DELETE":

            delete_count += 1

            return httpx.Response(200)

        return httpx.Response(500)

    client = create_client(handler)

    with pytest.raises(ClusterOperationError) as error:
        client.create_group("group-123")

    result = error.value.result

    assert result["success"] is False
    assert result["rollback_success"] is True

    assert post_count == 2
    assert delete_count == 1

    client.close()



# DELETE rollback

def test_delete_rolls_back_previous_nodes_when_later_node_fails():

    delete_count = 0
    post_count = 0

    def handler(request):
        nonlocal delete_count
        nonlocal post_count

        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "groupId": "group-123"
                },
            )

        if request.method == "DELETE":

            delete_count += 1

            if delete_count == 1:
                return httpx.Response(200)

            return httpx.Response(500)

        if request.method == "POST":

            post_count += 1

            return httpx.Response(201)

        return httpx.Response(500)

    client = create_client(handler)

    with pytest.raises(ClusterOperationError) as error:
        client.delete_group("group-123")

    result = error.value.result

    assert result["success"] is False
    assert result["rollback_success"] is True

    assert delete_count == 2
    assert post_count == 1

    client.close()



# Rollback failure

def test_create_reports_failed_rollback():

    post_count = 0

    def handler(request):
        nonlocal post_count

        if request.method == "GET":
            return httpx.Response(404)

        if request.method == "POST":

            post_count += 1

            if post_count == 1:
                return httpx.Response(201)

            return httpx.Response(400)

        if request.method == "DELETE":
            return httpx.Response(500)

        return httpx.Response(500)

    client = create_client(handler)

    with pytest.raises(ClusterOperationError) as error:
        client.create_group("group-123")

    result = error.value.result

    assert result["success"] is False
    assert result["rollback_success"] is False

    client.close()
