import pytest

from src.query import query


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_query():
    query_result = await query("tetris")
    assert query_result["result"][0]["Title"] == 'chvin/react-tetris'


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_query_user():
    query_result = await query("garulf/")
    for result in query_result["result"]:
        assert result["Title"].startswith("Garulf/")
