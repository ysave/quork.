import discord
from discord import app_commands

from utils import send_ephemeral_temp, send_error, guild_only, requires_db
from permissions import UNTIMEOUT, CHANGE_NICKNAME, has_permission, is_admin


def setup_moderation_commands(bot):
    """Set up moderation commands."""

    mod_group = app_commands.Group(name="mod", description="Moderation commands")

    @mod_group.command(name="untimeout", description="Remove timeout from a member")
    @app_commands.describe(member="The member to untimeout")
    @guild_only
    @requires_db(bot)
    async def untimeout_member(interaction: discord.Interaction, member: discord.Member):
        if not is_admin(interaction.user.id) and not await has_permission(
            bot.pool, interaction.guild_id, interaction.user.id, UNTIMEOUT
        ):
            return await send_error(interaction, "You don't have permission to untimeout members.")

        try:
            await member.timeout(None, reason=f"Timeout removed by {interaction.user}")
            embed = discord.Embed(
                description=f"Removed timeout from {member.mention}",
                color=discord.Color.green()
            )
            await send_ephemeral_temp(interaction, embed=embed)
        except discord.Forbidden:
            await send_error(interaction, "I don't have permission to untimeout this member.")
        except Exception as e:
            print(f"Error removing timeout: {e}")
            await send_error(interaction, "Failed to remove timeout.")

    @mod_group.command(name="nickname", description="Change a member's nickname")
    @app_commands.describe(member="The member to change nickname for", nickname="The new nickname (leave empty to reset)")
    @guild_only
    @requires_db(bot)
    async def change_nickname(interaction: discord.Interaction, member: discord.Member, nickname: str | None = None):
        if not is_admin(interaction.user.id) and not await has_permission(
            bot.pool, interaction.guild_id, interaction.user.id, CHANGE_NICKNAME
        ):
            return await send_error(interaction, "You don't have permission to change nicknames.")

        try:
            old_nick = member.display_name
            await member.edit(nick=nickname, reason=f"Nickname changed by {interaction.user}")
            new_nick = nickname or member.name
            embed = discord.Embed(
                description=f"Changed {member.mention}'s nickname from **{old_nick}** to **{new_nick}**",
                color=discord.Color.green()
            )
            await send_ephemeral_temp(interaction, embed=embed)
        except discord.Forbidden:
            await send_error(interaction, "I don't have permission to change this member's nickname.")
        except Exception as e:
            print(f"Error changing nickname: {e}")
            await send_error(interaction, "Failed to change nickname.")

    bot.tree.add_command(mod_group)
