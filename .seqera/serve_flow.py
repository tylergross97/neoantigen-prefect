"""Minimal diagnostic deployment — no codebase dependencies."""
from prefect import flow


@flow
def test_flow(message: str = "hello"):
    print(message)


if __name__ == "__main__":
    test_flow.serve(name="test-deployment")
