import pytest

from src.query import query


@pytest.mark.vcr
def test_query():
    assert query("tetris")["result"][0]["Title"] == 'chvin/react-tetris'


@pytest.mark.vcr
def test_query_user():
    query_result = query("garulf/")
    for result in query_result["result"]:
        assert result["Title"].startswith("Garulf/")
