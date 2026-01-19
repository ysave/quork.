from config import ADMIN_IDS

# Available permissions
EDIT_OWN = "edit_own"        # Can edit own quotes
EDIT_ALL = "edit_all"        # Can edit any quote
REMOVE_OWN = "remove_own"    # Can remove own quotes
REMOVE_ALL = "remove_all"    # Can remove any quote
UNTIMEOUT = "untimeout"      # Can untimeout members
CHANGE_NICKNAME = "change_nickname"  # Can change other members' nicknames

ALL_PERMISSIONS = [EDIT_OWN, EDIT_ALL, REMOVE_OWN, REMOVE_ALL, UNTIMEOUT, CHANGE_NICKNAME]

PERMISSION_NAMES = {
    EDIT_OWN: "Edit own quotes",
    EDIT_ALL: "Edit all quotes",
    REMOVE_OWN: "Remove own quotes",
    REMOVE_ALL: "Remove all quotes",
    UNTIMEOUT: "Untimeout members",
    CHANGE_NICKNAME: "Change nicknames",
}


def is_admin(user_id: int) -> bool:
    """Check if user is a bot admin (can grant/revoke permissions)."""
    return user_id in ADMIN_IDS


async def has_permission(pool, guild_id: int, user_id: int, permission: str) -> bool:
    """Check if user has a specific permission."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM permissions WHERE guild_id=$1 AND user_id=$2 AND permission=$3",
            guild_id, user_id, permission
        )
    return row is not None


async def can_edit(pool, guild_id: int, user_id: int) -> tuple[bool, bool]:
    """
    Check if user can edit quotes.
    Returns (can_edit_own, can_edit_all)
    """
    perms = await get_user_permissions(pool, guild_id, user_id)
    can_edit_all = EDIT_ALL in perms
    can_edit_own = EDIT_OWN in perms or can_edit_all
    return can_edit_own, can_edit_all


async def can_remove(pool, guild_id: int, user_id: int) -> tuple[bool, bool]:
    """
    Check if user can remove quotes.
    Returns (can_remove_own, can_remove_all)
    """
    perms = await get_user_permissions(pool, guild_id, user_id)
    can_remove_all = REMOVE_ALL in perms
    can_remove_own = REMOVE_OWN in perms or can_remove_all
    return can_remove_own, can_remove_all


async def grant_permission(pool, guild_id: int, user_id: int, permission: str, granted_by: int) -> bool:
    """Grant a permission to a user. Returns True if successful."""
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO permissions (guild_id, user_id, permission, granted_by)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (guild_id, user_id, permission) DO NOTHING""",
                guild_id, user_id, permission, granted_by
            )
        return True
    except Exception:
        return False


async def revoke_permission(pool, guild_id: int, user_id: int, permission: str) -> bool:
    """Revoke a permission from a user. Returns True if revoked."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM permissions WHERE guild_id=$1 AND user_id=$2 AND permission=$3",
            guild_id, user_id, permission
        )
    return result != "DELETE 0"


async def get_user_permissions(pool, guild_id: int, user_id: int) -> list[str]:
    """Get all permissions for a user in a guild."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT permission FROM permissions WHERE guild_id=$1 AND user_id=$2",
            guild_id, user_id
        )
    return [row['permission'] for row in rows]


async def get_users_with_permission(pool, guild_id: int, permission: str) -> list[int]:
    """Get all user IDs that have a specific permission in a guild."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id FROM permissions WHERE guild_id=$1 AND permission=$2",
            guild_id, permission
        )
    return [row['user_id'] for row in rows]
