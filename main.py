from cluster_client import ClusterClient


def main():
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


if __name__ == "__main__":
    main()