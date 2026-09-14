import time
from enum import Enum
import httpx


class GroupState(str, Enum):
    """
    Possible states returned by a node operation.
    """

    PRESENT = "present"
    ABSENT = "absent"
    CREATED = "created"
    DELETED = "deleted"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ClusterOperationError(Exception):
    """Raised when a create or delete operation fails."""

    def __init__(self, message, result):
        super().__init__(message)
        self.result = result


class CheckError(Exception):
    """Raised when we cannot check the nodes before starting."""

    def __init__(self, message, results):
        super().__init__(message)
        self.results = results


class NodeClient:
    """
    Talks to one cluster node.
    """

    def __init__(
        self,
        host,
        http_client,
        retries=2,
        backoff_seconds=0.5,
    ):
        self.host = host
        self.http_client = http_client

        # Number of retries after the first attempt.
        # retries=2 means 3 total attempts.
        self.retries = retries
        self.backoff_seconds = backoff_seconds

    def _sleep_before_retry(self, attempt):
        # Exponential backoff: 0.5s, 1s, 2s, 4s, ...
        delay = self.backoff_seconds * (2 ** (attempt - 1))
        time.sleep(delay)

    def get_group(self, group_id):
        """
        Check whether the group exists on this node.
        """

        url = f"http://{self.host}/v1/group/{group_id}/"
        max_attempts = self.retries + 1

        last_reason = ""
        last_status_code = None

        for attempt in range(1, max_attempts + 1):
            try:
                response = self.http_client.get(url)

                last_status_code = response.status_code

                if response.status_code == 200:
                    return {
                        "host": self.host,
                        "state": GroupState.PRESENT,
                        "status_code": 200,
                        "attempts": attempt,
                        "reason": "Group exists on this node.",
                    }

                if response.status_code == 404:
                    return {
                        "host": self.host,
                        "state": GroupState.ABSENT,
                        "status_code": 404,
                        "attempts": attempt,
                        "reason": "Group does not exist on this node.",
                    }

                last_reason = (
                    f"GET group failed with HTTP {response.status_code}."
                )

            except httpx.TimeoutException:
                last_reason = "GET request timed out."

            except httpx.RequestError as exc:
                last_reason = f"GET request failed: {exc}"

            if attempt < max_attempts:
                self._sleep_before_retry(attempt)

        return {
            "host": self.host,
            "state": GroupState.UNKNOWN,
            "status_code": last_status_code,
            "attempts": max_attempts,
            "reason": f"Could not determine group state. {last_reason}",
        }

    def create_group(self, group_id):
        """
        Create the group on this node.
        """

        url = f"http://{self.host}/v1/group/"
        max_attempts = self.retries + 1

        last_reason = ""
        last_status_code = None

        for attempt in range(1, max_attempts + 1):
            try:
                response = self.http_client.post(
                    url,
                    json={"groupId": group_id},
                )

                last_status_code = response.status_code

                if response.status_code == 201:
                    return {
                        "host": self.host,
                        "state": GroupState.CREATED,
                        "changed": True,
                        "status_code": 201,
                        "attempts": attempt,
                        "reason": "Group was created successfully.",
                    }

                if response.status_code == 400:
                    # 400 is not considered a transient error.
                    return {
                        "host": self.host,
                        "state": GroupState.FAILED,
                        "changed": False,
                        "status_code": 400,
                        "attempts": attempt,
                        "reason": (
                            "Server rejected the create request. "
                            "The group may already exist."
                        ),
                    }

                if response.status_code == 500:
                    last_reason = (
                        "Server returned HTTP 500 Internal Server Error."
                    )
                else:
                    return {
                        "host": self.host,
                        "state": GroupState.FAILED,
                        "changed": False,
                        "status_code": response.status_code,
                        "attempts": attempt,
                        "reason": (
                            f"Unexpected HTTP status "
                            f"{response.status_code}."
                        ),
                    }

            except httpx.TimeoutException:
                last_reason = "POST request timed out."

            except httpx.RequestError as exc:
                last_reason = f"POST request failed: {exc}"

            # The request may have succeeded even if the response was lost.
            # Check the current state before deciding whether to retry.
            if last_reason:
                state_result = self.get_group(group_id)

                if state_result["state"] == GroupState.PRESENT:
                    return {
                        "host": self.host,
                        "state": GroupState.UNKNOWN,
                        "changed": False,
                        "status_code": last_status_code,
                        "attempts": attempt,
                        "reason": (
                            f"{last_reason} A following GET returned HTTP 200, "
                            "so the group exists, but we cannot prove that "
                            "this operation created it. The change will not "
                            "be rolled back automatically."
                        ),
                    }

                if state_result["state"] == GroupState.UNKNOWN:
                    return {
                        "host": self.host,
                        "state": GroupState.UNKNOWN,
                        "changed": False,
                        "status_code": last_status_code,
                        "attempts": attempt,
                        "reason": (
                            f"{last_reason} A following GET could not "
                            "determine the group state."
                        ),
                    }

                if attempt < max_attempts:
                    self._sleep_before_retry(attempt)
                    continue

        return {
            "host": self.host,
            "state": GroupState.FAILED,
            "changed": False,
            "status_code": last_status_code,
            "attempts": max_attempts,
            "reason": (
                f"Create failed after {max_attempts} attempts. "
                f"{last_reason}"
            ),
        }

    def delete_group(self, group_id):
        """
        Delete the group from this node.
        """

        url = f"http://{self.host}/v1/group/"
        max_attempts = self.retries + 1

        last_reason = ""
        last_status_code = None

        for attempt in range(1, max_attempts + 1):
            try:
                response = self.http_client.request(
                    "DELETE",
                    url,
                    json={"groupId": group_id},
                )

                last_status_code = response.status_code

                if response.status_code == 200:
                    return {
                        "host": self.host,
                        "state": GroupState.DELETED,
                        "changed": True,
                        "status_code": 200,
                        "attempts": attempt,
                        "reason": "Group was deleted successfully.",
                    }

                if response.status_code == 404:
                    # The desired state is already reached.
                    return {
                        "host": self.host,
                        "state": GroupState.DELETED,
                        "changed": False,
                        "status_code": 404,
                        "attempts": attempt,
                        "reason": (
                            "Group was already absent. "
                            "Delete was treated as a successful no-op."
                        ),
                    }

                if response.status_code == 500:
                    last_reason = (
                        "Server returned HTTP 500 Internal Server Error."
                    )
                else:
                    return {
                        "host": self.host,
                        "state": GroupState.FAILED,
                        "changed": False,
                        "status_code": response.status_code,
                        "attempts": attempt,
                        "reason": (
                            f"Unexpected HTTP status "
                            f"{response.status_code}."
                        ),
                    }

            except httpx.TimeoutException:
                last_reason = "DELETE request timed out."

            except httpx.RequestError as exc:
                last_reason = f"DELETE request failed: {exc}"

            # Check whether the delete actually happened before retrying.
            if last_reason:
                state_result = self.get_group(group_id)

                if state_result["state"] == GroupState.ABSENT:
                    return {
                        "host": self.host,
                        "state": GroupState.UNKNOWN,
                        "changed": False,
                        "status_code": last_status_code,
                        "attempts": attempt,
                        "reason": (
                            f"{last_reason} A following GET returned HTTP 404, "
                            "so the group is absent, but we cannot prove that "
                            "this operation deleted it. The change will not "
                            "be rolled back automatically."
                        ),
                    }

                if state_result["state"] == GroupState.UNKNOWN:
                    return {
                        "host": self.host,
                        "state": GroupState.UNKNOWN,
                        "changed": False,
                        "status_code": last_status_code,
                        "attempts": attempt,
                        "reason": (
                            f"{last_reason} A following GET could not "
                            "determine the group state."
                        ),
                    }

                if attempt < max_attempts:
                    self._sleep_before_retry(attempt)
                    continue

        return {
            "host": self.host,
            "state": GroupState.FAILED,
            "changed": False,
            "status_code": last_status_code,
            "attempts": max_attempts,
            "reason": (
                f"Delete failed after {max_attempts} attempts. "
                f"{last_reason}"
            ),
        }


class ClusterClient:
    """
    Creates and deletes groups across all cluster nodes.
    """

    def __init__(
        self,
        hosts,
        retries=2,
        backoff_seconds=0.5,
        timeout=5.0,
        http_client=None,
    ):
        self.hosts = hosts
        self.retries = retries
        self.backoff_seconds = backoff_seconds

        if http_client is None:
            self.http_client = httpx.Client(timeout=timeout)
            self.should_close_http_client = True
        else:
            self.http_client = http_client
            self.should_close_http_client = False

        self.nodes = []

        for host in hosts:
            node = NodeClient(
                host=host,
                http_client=self.http_client,
                retries=retries,
                backoff_seconds=backoff_seconds,
            )

            self.nodes.append(node)

    def close(self):
        """Close the HTTP client if this class created it."""

        if self.should_close_http_client:
            self.http_client.close()

    def _check_before_operation(self, group_id, operation):
        """
        Check every node before making any changes.
        """

        results = []

        for node in self.nodes:
            result = node.get_group(group_id)
            results.append(result)

            if result["state"] == GroupState.UNKNOWN:
                raise CheckError(
                    (
                        f"Could not check node {node.host} before starting "
                        "the operation. No mutation was performed."
                    ),
                    results,
                )

        if operation == "create":
            for result in results:
                if result["state"] == GroupState.PRESENT:
                    raise ClusterOperationError(
                        (
                            f"Create cannot start because the group already "
                            f"exists on node {result['host']}."
                        ),
                        {
                            "operation": "create",
                            "group_id": group_id,
                            "success": False,
                            "reason": (
                                "Group already exists on at least one node."
                            ),
                            "nodes": results,
                            "rollback": [],
                            "rollback_success": True,
                        },
                    )

        return results

    def create_group(self, group_id):
        """
        Create the group on every node.

        If a node fails after previous nodes succeeded,
        rollback the successful changes.
        """

        self._check_before_operation(group_id, "create")

        operation_results = []

        for node in self.nodes:
            result = node.create_group(group_id)
            operation_results.append(result)

            if result["state"] != GroupState.CREATED:
                rollback_results = self._rollback_create(
                    group_id,
                    operation_results,
                )

                rollback_success = all(
                    r["success"] for r in rollback_results
                )

                final_result = {
                    "operation": "create",
                    "group_id": group_id,
                    "success": False,
                    "reason": (
                        f"Create failed on node {node.host}. "
                        f"Reason: {result['reason']}"
                    ),
                    "nodes": operation_results,
                    "rollback": rollback_results,
                    "rollback_success": rollback_success,
                }

                raise ClusterOperationError(
                    "Cluster create operation failed.",
                    final_result,
                )

        return {
            "operation": "create",
            "group_id": group_id,
            "success": True,
            "reason": "Group was created successfully on all nodes.",
            "nodes": operation_results,
            "rollback": [],
            "rollback_success": True,
        }

    def delete_group(self, group_id):
        """
        Delete the group from every node.

        If a node fails after previous nodes succeeded,
        rollback the successful changes.
        """

        self._check_before_operation(group_id, "delete")

        operation_results = []

        for node in self.nodes:
            result = node.delete_group(group_id)
            operation_results.append(result)

            if result["state"] != GroupState.DELETED:
                rollback_results = self._rollback_delete(
                    group_id,
                    operation_results,
                )

                rollback_success = all(
                    r["success"] for r in rollback_results
                )

                final_result = {
                    "operation": "delete",
                    "group_id": group_id,
                    "success": False,
                    "reason": (
                        f"Delete failed on node {node.host}. "
                        f"Reason: {result['reason']}"
                    ),
                    "nodes": operation_results,
                    "rollback": rollback_results,
                    "rollback_success": rollback_success,
                }

                raise ClusterOperationError(
                    "Cluster delete operation failed.",
                    final_result,
                )

        return {
            "operation": "delete",
            "group_id": group_id,
            "success": True,
            "reason": "Group was deleted successfully from all nodes.",
            "nodes": operation_results,
            "rollback": [],
            "rollback_success": True,
        }

    def _rollback_create(self, group_id, operation_results):
        """
        Undo successful creates in reverse order.
        """

        rollback_results = []

        for result in reversed(operation_results):
            if (
                result["state"] == GroupState.CREATED
                and result["changed"] is True
            ):
                node = self._find_node(result["host"])

                if node is None:
                    rollback_results.append({
                        "host": result["host"],
                        "success": False,
                        "reason": "Node was not found for rollback.",
                    })
                    continue

                rollback = node.delete_group(group_id)

                if rollback["state"] == GroupState.DELETED:
                    rollback_results.append({
                        "host": result["host"],
                        "success": True,
                        "reason": (
                            "Rollback delete succeeded. "
                            f"{rollback['reason']}"
                        ),
                    })
                else:
                    rollback_results.append({
                        "host": result["host"],
                        "success": False,
                        "reason": (
                            "Rollback delete failed. "
                            f"{rollback['reason']}"
                        ),
                    })

        return rollback_results

    def _rollback_delete(self, group_id, operation_results):
        """
        Undo successful deletes in reverse order.
        """

        rollback_results = []

        for result in reversed(operation_results):
            if (
                result["state"] == GroupState.DELETED
                and result["changed"] is True
            ):
                node = self._find_node(result["host"])

                if node is None:
                    rollback_results.append({
                        "host": result["host"],
                        "success": False,
                        "reason": "Node was not found for rollback.",
                    })
                    continue

                rollback = node.create_group(group_id)

                if rollback["state"] == GroupState.CREATED:
                    rollback_results.append({
                        "host": result["host"],
                        "success": True,
                        "reason": (
                            "Rollback create succeeded. "
                            f"{rollback['reason']}"
                        ),
                    })
                else:
                    rollback_results.append({
                        "host": result["host"],
                        "success": False,
                        "reason": (
                            "Rollback create failed. "
                            f"{rollback['reason']}"
                        ),
                    })

        return rollback_results

    def _find_node(self, host):
        """Find a node by its host name."""

        for node in self.nodes:
            if node.host == host:
                return node

        return None