import os


def pytest_configure() -> None:
    os.environ["DJANGO_TEST"] = "1"
