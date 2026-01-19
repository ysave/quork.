import discord
from discord import app_commands

from permissions import (
    UNTIMEOUT, CHANGE_NICKNAME, is_admin, has_permission
)

# Commands that require specific permissions to see
PERMISSION_REQUIRED = {
    "/mod untimeout": UNTIMEOUT,
    "/mod nickname": CHANGE_NICKNAME,
}


def setup_help_command(bot):
    """Set up the help command that auto-discovers all commands."""

    @bot.tree.command(name="help", description="Show all available commands")
    async def help_command(interaction: discord.Interaction):
        embed = discord.Embed(
            title="Bot Commands",
            description="Here are all available commands:",
            color=discord.Color.blurple(),
        )

        user_is_admin = is_admin(interaction.user.id)

        # Group commands by category
        categories: dict[str, list[tuple[str, str]]] = {}

        for command in bot.tree.get_commands():
            if isinstance(command, app_commands.Group):
                # It's a command group (like /quote)
                category = command.name.capitalize()
                if category not in categories:
                    categories[category] = []

                for subcommand in command.commands:
                    cmd_name = f"/{command.name} {subcommand.name}"

                    # Check if user has permission to see this command
                    required_perm = PERMISSION_REQUIRED.get(cmd_name)
                    if required_perm and not user_is_admin:
                        if bot.pool:
                            has_perm = await has_permission(
                                bot.pool, interaction.guild_id, interaction.user.id, required_perm
                            )
                            if not has_perm:
                                continue
                        else:
                            continue

                    categories[category].append((cmd_name, subcommand.description))
            else:
                # It's a standalone command
                category = "General"
                if category not in categories:
                    categories[category] = []
                categories[category].append((f"/{command.name}", command.description))

        # Remove empty categories
        categories = {k: v for k, v in categories.items() if v}

        # Sort categories, but put "General" last
        sorted_categories = sorted(
            categories.keys(),
            key=lambda x: (x == "General", x)
        )

        for category in sorted_categories:
            commands = categories[category]
            # Sort commands alphabetically within category
            commands.sort(key=lambda x: x[0])

            lines = [f"`{name}` - {desc}" for name, desc in commands]
            embed.add_field(
                name=f"**{category}**",
                value="\n".join(lines),
                inline=False,
            )

        embed.set_footer(text="Use /command to run a command")
        await interaction.response.send_message(embed=embed, ephemeral=True)
