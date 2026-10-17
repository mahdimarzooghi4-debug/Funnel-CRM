import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_runtime_role_is_non_owner_and_cannot_bypass_rls(
    runtime_session_factory,
) -> None:
    async with runtime_session_factory() as session:
        async with session.begin():
            result = (
                await session.execute(
                    text(
                        """
                        SELECT r.rolsuper, r.rolbypassrls, c.relrowsecurity,
                               c.relforcerowsecurity, pg_get_userbyid(c.relowner) AS table_owner,
                               current_user
                        FROM pg_roles AS r
                        JOIN pg_class AS c ON c.relname = 'workspaces'
                        WHERE r.rolname = current_user
                        """
                    )
                )
            ).one()

    assert result.rolsuper is False
    assert result.rolbypassrls is False
    assert result.relrowsecurity is True
    assert result.relforcerowsecurity is True
    assert result.table_owner != result.current_user
