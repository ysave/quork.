import random
import re
import discord
import asyncpg
from discord import app_commands

from config import WEB_URL
from utils import (
    send_ephemeral_temp, send_error, get_user_display_info, format_date,
    guild_only, requires_db, PaginatedView
)
from permissions import (
    EDIT_OWN, EDIT_ALL, REMOVE_OWN, REMOVE_ALL, UNTIMEOUT, CHANGE_NICKNAME,
    PERMISSION_NAMES, is_admin, can_edit, can_remove, grant_permission,
    revoke_permission, get_user_permissions, get_users_with_permission
)

# Terminal-style color (matches quork website)
CYAN = discord.Color.from_rgb(0, 255, 209)


async def get_quote_score(pool, quote_id: int) -> int:
    """Fetch the current score (upvotes - downvotes) for a quote."""
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT SUM(vote) FROM quote_votes WHERE quote_id=$1", quote_id)
    return val or 0


def create_quote_embed(quote_id: int, quote_text: str, author_name: str | None, date_str: str,
                       creator_name: str, creator_avatar: str | None,
                       color: discord.Color, score: int = 0, context: str | None = None) -> discord.Embed:
    """Create a formatted quote embed with terminal style."""
    lines = []
    lines.append(f"```ansi")
    lines.append(f"\u001b[1;37m> \u001b[0;37m\"{quote_text}\"")
    lines.append(f"```")

    if author_name:
        lines.append(f"@**{author_name}**")

    if context:
        lines.append(f"-# {context}")

    embed = discord.Embed(
        description="\n".join(lines),
        color=color,
    )

    score_str = f"+{score}" if score > 0 else str(score)
    embed.set_footer(text=f"[{score_str}]  •  {date_str}  •  {creator_name}  •  #{quote_id}", icon_url=creator_avatar)
    return embed


def create_quote_view(quote_id: int) -> discord.ui.View | None:
    """Create a view with a link button to the quote on the web."""
    if not WEB_URL:
        return None
    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        label="View on Web",
        url=f"{WEB_URL}/quotes/{quote_id}",
        style=discord.ButtonStyle.link
    ))
    return view


def setup_quote_commands(bot):
    """Set up all quote-related commands."""

    quote_group = app_commands.Group(name="quote", description="Manage and share quotes")
    perm_group = app_commands.Group(name="permissions", description="Manage quote permissions", parent=quote_group)

    # --- Quote Commands ---

    @quote_group.command(name="add", description="Add a new quote to the server")
    @app_commands.describe(quote="The quote text", author="Who said it (optional)", context="Additional context about the quote (optional)")
    @guild_only
    @requires_db(bot)
    async def add_quote(interaction: discord.Interaction, quote: str, author: str | None = None, context: str | None = None):
        await interaction.response.defer(ephemeral=True)
        try:
            async with bot.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """INSERT INTO quotes (guild_id, author_name, quote_text, context, added_by_id)
                       VALUES ($1, $2, $3, $4, $5) RETURNING id, created_at""",
                    interaction.guild_id, author, quote, context, interaction.user.id,
                )

            embed = create_quote_embed(
                row['id'], quote, author, format_date(row["created_at"]),
                interaction.user.display_name, interaction.user.display_avatar.url, CYAN, 0, context
            )
            await send_ephemeral_temp(interaction, embed=embed)
        except asyncpg.UniqueViolationError:
            await send_error(interaction, "This quote already exists in the server!")
        except Exception as e:
            print(f"Error adding quote: {e}")
            await send_error(interaction, "Failed to save the quote. Please try again.")

    @quote_group.command(name="random", description="Display a random quote from the server")
    @guild_only
    @requires_db(bot)
    async def random_quote(interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            async with bot.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id, author_name, quote_text, context, created_at, added_by_id FROM quotes WHERE guild_id=$1",
                    interaction.guild_id,
                )

            if not rows:
                return await send_error(interaction, "No quotes yet. Use `/quote add` to add one!")

            q = random.choice(rows)
            score = await get_quote_score(bot.pool, q['id'])
            creator_name, creator_avatar = await get_user_display_info(bot, interaction.guild, q["added_by_id"])

            embed = create_quote_embed(
                q["id"], q["quote_text"], q["author_name"], format_date(q["created_at"]),
                creator_name, creator_avatar, CYAN, score, q["context"]
            )
            view = create_quote_view(q["id"])
            if view:
                await interaction.followup.send(embed=embed, view=view)
            else:
                await interaction.followup.send(embed=embed)
            msg = await interaction.original_response()
            await msg.add_reaction("👍")
            await msg.add_reaction("👎")
        except Exception as e:
            import traceback
            print(f"Error getting random quote: {e}")
            traceback.print_exc()
            await send_error(interaction, "Failed to fetch quote. Please try again.")

    @quote_group.command(name="edit", description="Edit a quote")
    @app_commands.describe(search="Filter quotes by text, author, or context (optional)", author="Filter quotes by author (optional)")
    @guild_only
    @requires_db(bot)
    async def edit_quote(interaction: discord.Interaction, search: str | None = None, author: str | None = None):
        await interaction.response.defer(ephemeral=True)
        try:
            can_edit_own, can_edit_all = await can_edit(bot.pool, interaction.guild_id, interaction.user.id)

            if not can_edit_own and not can_edit_all:
                return await send_error(interaction, "You don't have permission to edit quotes.")

            if can_edit_all:
                query = "SELECT id, quote_text, author_name, context, added_by_id FROM quotes WHERE guild_id=$1"
                params = [interaction.guild_id]
            else:
                query = "SELECT id, quote_text, author_name, context, added_by_id FROM quotes WHERE guild_id=$1 AND added_by_id=$2"
                params = [interaction.guild_id, interaction.user.id]

            if search:
                p1 = len(params) + 1
                p2 = len(params) + 2
                p3 = len(params) + 3
                query += f" AND (quote_text ILIKE ${p1} OR COALESCE(author_name, '') ILIKE ${p2} OR COALESCE(context, '') ILIKE ${p3})"
                params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

            if author:
                query += f" AND author_name ILIKE ${len(params) + 1}"
                params.append(f"%{author}%")

            query += " ORDER BY created_at DESC"

            async with bot.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)

            if not rows:
                filters = []
                if search:
                    filters.append(f"text '{search}'")
                if author:
                    filters.append(f"author '{author}'")
                msg = f"No quotes matching {' and '.join(filters)}." if filters else "No quotes available to edit."
                return await send_error(interaction, msg)

            view = EditView(rows, interaction.user.id, interaction.guild_id, search, author, bot, can_edit_all)
            view.update_view()
            await interaction.followup.send(embed=view.create_embed(), view=view, ephemeral=True)
            view.message = await interaction.original_response()
        except Exception as e:
            print(f"Error in edit_quote: {e}")
            await send_error(interaction, "An error occurred. Please try again.")

    @quote_group.command(name="remove", description="Remove a quote")
    @app_commands.describe(search="Filter quotes by text (optional)", author="Filter quotes by author (optional)", context="Filter quotes by context (optional)")
    @guild_only
    @requires_db(bot)
    async def remove_quote(interaction: discord.Interaction, search: str | None = None, author: str | None = None, context: str | None = None):
        await interaction.response.defer(ephemeral=True)
        try:
            can_remove_own, can_remove_all = await can_remove(bot.pool, interaction.guild_id, interaction.user.id)

            if not can_remove_own and not can_remove_all:
                return await send_error(interaction, "You don't have permission to remove quotes.")

            if can_remove_all:
                query = "SELECT id, quote_text, author_name, context, added_by_id FROM quotes WHERE guild_id=$1"
                params = [interaction.guild_id]
            else:
                query = "SELECT id, quote_text, author_name, context, added_by_id FROM quotes WHERE guild_id=$1 AND added_by_id=$2"
                params = [interaction.guild_id, interaction.user.id]

            if search:
                query += f" AND quote_text ILIKE ${len(params) + 1}"
                params.append(f"%{search}%")

            if author:
                query += f" AND author_name ILIKE ${len(params) + 1}"
                params.append(f"%{author}%")

            if context:
                query += f" AND context ILIKE ${len(params) + 1}"
                params.append(f"%{context}%")

            query += " ORDER BY created_at DESC"

            async with bot.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)

            if not rows:
                filters = []
                if search:
                    filters.append(f"text '{search}'")
                if author:
                    filters.append(f"author '{author}'")
                if context:
                    filters.append(f"context '{context}'")
                msg = f"No quotes matching {' and '.join(filters)}." if filters else "No quotes available to remove."
                return await send_error(interaction, msg)

            view = RemoveView(rows, interaction.user.id, interaction.guild_id, search, author, bot, can_remove_all)
            view.update_view()
            await interaction.followup.send(embed=view.create_embed(), view=view, ephemeral=True)
            view.message = await interaction.original_response()
        except Exception as e:
            print(f"Error in remove_quote: {e}")
            await send_error(interaction, "An error occurred. Please try again.")

    @quote_group.command(name="find", description="Search for a quote and post it publicly")
    @app_commands.describe(search="Text to search for in quotes (optional)", author="Author to search for (optional)", context="Context to search for (optional)")
    @guild_only
    @requires_db(bot)
    async def find_quote(interaction: discord.Interaction, search: str | None = None, author: str | None = None, context: str | None = None):
        await interaction.response.defer(ephemeral=True)
        if not search and not author and not context:
            return await send_error(interaction, "Please provide at least a search term, author, or context.")

        try:
            query = "SELECT id, quote_text, author_name, context, created_at, added_by_id FROM quotes WHERE guild_id=$1"
            params = [interaction.guild_id]

            if search:
                query += f" AND quote_text ILIKE ${len(params) + 1}"
                params.append(f"%{search}%")

            if author:
                query += f" AND author_name ILIKE ${len(params) + 1}"
                params.append(f"%{author}%")

            if context:
                query += f" AND context ILIKE ${len(params) + 1}"
                params.append(f"%{context}%")

            query += " ORDER BY created_at DESC"

            async with bot.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)

            if not rows:
                filters = []
                if search:
                    filters.append(f"text '{search}'")
                if author:
                    filters.append(f"author '{author}'")
                if context:
                    filters.append(f"context '{context}'")
                return await send_error(interaction, f"No quotes matching {' and '.join(filters)}.")

            view = FindView(rows, interaction.user.id, search, author, bot)
            view.update_view()
            await interaction.followup.send(embed=view.create_embed(), view=view, ephemeral=True)
            view.message = await interaction.original_response()
        except Exception as e:
            print(f"Error in find_quote: {e}")
            await send_error(interaction, "An error occurred. Please try again.")

    # --- Permission Commands ---

    @perm_group.command(name="grant", description="Grant a permission to a user (admin only)")
    @app_commands.describe(user="The user to grant permission to", permission="The permission to grant")
    @app_commands.choices(permission=[
        app_commands.Choice(name="Edit own quotes", value=EDIT_OWN),
        app_commands.Choice(name="Edit all quotes", value=EDIT_ALL),
        app_commands.Choice(name="Remove own quotes", value=REMOVE_OWN),
        app_commands.Choice(name="Remove all quotes", value=REMOVE_ALL),
        app_commands.Choice(name="Untimeout members", value=UNTIMEOUT),
        app_commands.Choice(name="Change nicknames", value=CHANGE_NICKNAME),
    ])
    @guild_only
    @requires_db(bot)
    async def grant_perm(interaction: discord.Interaction, user: discord.Member, permission: str):
        if not is_admin(interaction.user.id):
            return await send_error(interaction, "Only bot admins can grant permissions.")

        await grant_permission(bot.pool, interaction.guild_id, user.id, permission, interaction.user.id)
        perm_name = PERMISSION_NAMES.get(permission, permission)
        embed = discord.Embed(description=f"Granted **{perm_name}** to {user.mention}", color=discord.Color.green())
        await send_ephemeral_temp(interaction, embed=embed)

    @perm_group.command(name="revoke", description="Revoke a permission from a user (admin only)")
    @app_commands.describe(user="The user to revoke permission from", permission="The permission to revoke")
    @app_commands.choices(permission=[
        app_commands.Choice(name="Edit own quotes", value=EDIT_OWN),
        app_commands.Choice(name="Edit all quotes", value=EDIT_ALL),
        app_commands.Choice(name="Remove own quotes", value=REMOVE_OWN),
        app_commands.Choice(name="Remove all quotes", value=REMOVE_ALL),
        app_commands.Choice(name="Untimeout members", value=UNTIMEOUT),
        app_commands.Choice(name="Change nicknames", value=CHANGE_NICKNAME),
    ])
    @guild_only
    @requires_db(bot)
    async def revoke_perm(interaction: discord.Interaction, user: discord.Member, permission: str):
        if not is_admin(interaction.user.id):
            return await send_error(interaction, "Only bot admins can revoke permissions.")

        revoked = await revoke_permission(bot.pool, interaction.guild_id, user.id, permission)
        perm_name = PERMISSION_NAMES.get(permission, permission)
        color = discord.Color.orange()
        desc = f"Revoked **{perm_name}** from {user.mention}" if revoked else f"{user.mention} didn't have **{perm_name}**"
        await send_ephemeral_temp(interaction, embed=discord.Embed(description=desc, color=color))

    @perm_group.command(name="list", description="List all users with special permissions (admin only)")
    @guild_only
    @requires_db(bot)
    async def list_perms(interaction: discord.Interaction):
        if not is_admin(interaction.user.id):
            return await send_error(interaction, "Only bot admins can view all permissions.")

        try:
            embed = discord.Embed(title="Quote Permissions", color=discord.Color.blurple())
            for perm_key, perm_name in PERMISSION_NAMES.items():
                users = await get_users_with_permission(bot.pool, interaction.guild_id, perm_key)
                val = "\n".join([f"<@{uid}>" for uid in users]) if users else "*No users*"
                embed.add_field(name=perm_name, value=val, inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            print(f"Error listing permissions: {e}")
            await send_error(interaction, "An error occurred. Please try again.")

    @perm_group.command(name="check", description="Check your own permissions")
    @guild_only
    @requires_db(bot)
    async def check_perms(interaction: discord.Interaction):
        try:
            perms = await get_user_permissions(bot.pool, interaction.guild_id, interaction.user.id)
            embed = discord.Embed(title="Your Permissions", color=discord.Color.blurple())
            if perms:
                perm_names = [PERMISSION_NAMES.get(p, p) for p in perms]
                embed.description = "\n".join(f"• {p}" for p in perm_names)
            else:
                embed.description = "You have no permissions.\nYou can only add quotes and use find/random."
            if is_admin(interaction.user.id):
                embed.set_footer(text="You are a bot admin (can grant/revoke permissions)")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            print(f"Error checking permissions: {e}")
            await send_error(interaction, "An error occurred. Please try again.")

    # --- Reaction Listeners ---
    
    async def on_reaction_change(payload: discord.RawReactionActionEvent, added: bool):
        try:
            if not bot.user or payload.user_id == bot.user.id:
                return

            emoji = str(payload.emoji)
            if emoji not in ('👍', '👎'):
                return

            if not bot.pool:
                return

            channel = bot.get_channel(payload.channel_id)
            if not channel:
                return

            try:
                message = await channel.fetch_message(payload.message_id)
            except discord.NotFound:
                return

            if message.author.id != bot.user.id or not message.embeds:
                return

            embed = message.embeds[0]
            if not embed.footer or not embed.footer.text:
                return

             # Match quote ID at the end of footer: "... • #123"                       
            match = re.search(r"#(\d+)$", embed.footer.text)
            if not match:
                return

            quote_id = int(match.group(1))
            vote_val = 1 if emoji == '👍' else -1

            updated = False
            if added:
                # Add or update vote
                async with bot.pool.acquire() as conn:
                    # Upsert
                    await conn.execute(
                        """INSERT INTO quote_votes (quote_id, user_id, vote) VALUES ($1, $2, $3)
                           ON CONFLICT (quote_id, user_id) DO UPDATE SET vote=$3""",
                        quote_id, payload.user_id, vote_val
                    )
                updated = True
            else:
                # Remove vote only if it matches
                async with bot.pool.acquire() as conn:
                    result = await conn.execute(
                        "DELETE FROM quote_votes WHERE quote_id=$1 AND user_id=$2 AND vote=$3",
                        quote_id, payload.user_id, vote_val
                    )
                    if result != "DELETE 0":
                        updated = True

            if updated:
                # Remove the opposite reaction from this user
                if added:
                    opposite_emoji = '👎' if emoji == '👍' else '👍'
                    try:
                        await message.remove_reaction(opposite_emoji, payload.member or await bot.fetch_user(payload.user_id))
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        pass

                new_score = await get_quote_score(bot.pool, quote_id)
                # Update "[+X]" or "[-X]" or "[0]" in footer                          
                score_str = f"+{new_score}" if new_score > 0 else str(new_score)                                                                        
                new_footer = re.sub(r"\[[+\-]?\d+\]", f"[{score_str}]", embed.footer.text)  
                embed.set_footer(text=new_footer, icon_url=embed.footer.icon_url)
                await message.edit(embed=embed)
        except Exception as e:
            print(f"Error handling reaction: {e}")

    @bot.event
    async def on_raw_reaction_add(payload):
        await on_reaction_change(payload, added=True)

    @bot.event
    async def on_raw_reaction_remove(payload):
        await on_reaction_change(payload, added=False)
    
    bot.tree.add_command(quote_group)


# --- Views ---

class QuoteListEmbed:
    """Mixin for creating quote list embeds."""

    def create_embed(self) -> discord.Embed:
        page_rows = self.get_page_rows()
        lines = []
        for idx, row in enumerate(page_rows, 1):
            text = row["quote_text"]
            line = f'**{idx}.** "{text[:100]}..."' if len(text) > 100 else f'**{idx}.** "{text}"'
            
            extras = []
            if row.get('author_name'):
                extras.append(f"~ {row['author_name']}")
            if getattr(self, 'show_owner', False) and row.get('added_by_id'):
                extras.append(f"<@{row['added_by_id']}>")
            
            if extras:
                line += f" ({' | '.join(extras)})"
                
            lines.append(line)

        description = "\n".join(lines)
        if self.total_pages > 1:
            description += f"\n\n*Page {self.page + 1}/{self.total_pages} ({len(self.rows)} quotes)*"

        embed = discord.Embed(description=description, color=discord.Color.blue())
        embed.set_footer(text=self.get_footer_text())
        return embed


class EditView(QuoteListEmbed, PaginatedView):
    """View for selecting and editing quotes."""

    def __init__(self, rows, user_id, guild_id, search_text, author_text, bot, can_edit_all):
        super().__init__(rows, user_id)
        self.guild_id = guild_id
        self.search_text = search_text
        self.author_text = author_text
        self.bot = bot
        self.show_owner = can_edit_all

    def get_select_placeholder(self):
        return "Choose a quote to edit..."

    def get_footer_text(self):
        filters = []
        if self.search_text:
            filters.append(f"text: '{self.search_text}'")
        if self.author_text:
            filters.append(f"author: '{self.author_text}'")
        base = "Select a quote to edit it"
        return f"{' | '.join(filters)} | {base}" if filters else base

    async def on_select(self, interaction: discord.Interaction, quote_id: int):
        quote = next((r for r in self.rows if r['id'] == quote_id), None)
        if not quote:
            return await send_error(interaction, "Quote not found.")

        modal = EditQuoteModal(quote, self.bot, self.guild_id)
        await interaction.response.send_modal(modal)


class EditQuoteModal(discord.ui.Modal, title="Edit Quote"):
    """Modal for editing a quote."""

    def __init__(self, quote, bot, guild_id):
        super().__init__()
        self.quote = quote
        self.bot = bot
        self.guild_id = guild_id

        self.quote_text = discord.ui.TextInput(
            label="Quote",
            style=discord.TextStyle.paragraph,
            default=quote['quote_text'],
            max_length=1000,
        )
        self.add_item(self.quote_text)

        self.author_name = discord.ui.TextInput(
            label="Author (optional)",
            style=discord.TextStyle.short,
            default=quote['author_name'] or "",
            required=False,
            max_length=100,
        )
        self.add_item(self.author_name)

        self.context_input = discord.ui.TextInput(
            label="Context (optional)",
            style=discord.TextStyle.paragraph,
            default=quote.get('context') or "",
            required=False,
            max_length=500,
            placeholder="Additional context about the quote...",
        )
        self.add_item(self.context_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            async with self.bot.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE quotes SET quote_text=$1, author_name=$2, context=$3 WHERE id=$4 AND guild_id=$5",
                    self.quote_text.value,
                    self.author_name.value or None,
                    self.context_input.value or None,
                    self.quote['id'],
                    self.guild_id,
                )

            embed = discord.Embed(
                description=f"Quote **#{self.quote['id']}** has been updated.",
                color=discord.Color.green()
            )
            await send_ephemeral_temp(interaction, embed=embed)
        except Exception as e:
            print(f"Error updating quote: {e}")
            await send_error(interaction, "Failed to update quote. Please try again.")


class RemoveView(QuoteListEmbed, PaginatedView):
    """View for selecting and removing quotes."""

    def __init__(self, rows, user_id, guild_id, search_text, author_text, bot, can_remove_all):
        super().__init__(rows, user_id)
        self.guild_id = guild_id
        self.search_text = search_text
        self.author_text = author_text
        self.bot = bot
        self.show_owner = can_remove_all

    def get_select_placeholder(self):
        return "Choose a quote to remove..."

    def get_footer_text(self):
        filters = []
        if self.search_text:
            filters.append(f"text: '{self.search_text}'")
        if self.author_text:
            filters.append(f"author: '{self.author_text}'")
        base = "Select a quote to remove it"
        return f"{' | '.join(filters)} | {base}" if filters else base

    async def on_select(self, interaction: discord.Interaction, quote_id: int):
        try:
            async with self.bot.pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM quotes WHERE id=$1 AND guild_id=$2",
                    quote_id, self.guild_id,
                )

            if result == "DELETE 0":
                return await send_error(interaction, "Quote not found or already deleted.")

            embed = discord.Embed(description=f"Quote **#{quote_id}** removed.", color=discord.Color.green())
            await send_ephemeral_temp(interaction, embed=embed)

            self.rows = [r for r in self.rows if r['id'] != quote_id]
            self._update_total_pages()
            self.page = min(self.page, self.total_pages - 1)

            if not self.rows:
                await interaction.followup.edit_message(
                    interaction.message.id,
                    embed=discord.Embed(description="All quotes removed!", color=discord.Color.orange()),
                    view=None,
                )
            else:
                self.update_view()
                await interaction.followup.edit_message(
                    interaction.message.id, embed=self.create_embed(), view=self
                )
        except Exception as e:
            print(f"Error removing quote: {e}")
            await send_error(interaction, "Failed to remove quote. Please try again.")


class FindView(QuoteListEmbed, PaginatedView):
    """View for selecting and posting quotes."""

    def __init__(self, rows, user_id, search_text, author_text, bot):
        super().__init__(rows, user_id)
        self.search_text = search_text
        self.author_text = author_text
        self.bot = bot

    def get_select_placeholder(self):
        return "Choose a quote to post..."

    def get_footer_text(self):
        filters = []
        if self.search_text:
            filters.append(f"text: '{self.search_text}'")
        if self.author_text:
            filters.append(f"author: '{self.author_text}'")
        base = "Select a quote to post it"
        return f"{' | '.join(filters)} | {base}" if filters else base

    async def on_select(self, interaction: discord.Interaction, quote_id: int):
        quote = next((r for r in self.rows if r['id'] == quote_id), None)
        if not quote:
            return await send_error(interaction, "Quote not found.")

        score = await get_quote_score(self.bot.pool, quote['id'])
        creator_name, creator_avatar = await get_user_display_info(
            self.bot, interaction.guild, quote["added_by_id"]
        )
        embed = create_quote_embed(
            quote['id'], quote["quote_text"], quote["author_name"], format_date(quote["created_at"]),
            creator_name, creator_avatar, CYAN, score, quote.get("context")
        )
        view = create_quote_view(quote['id'])

        if view:
            await interaction.response.send_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed)
        try:
            msg = await interaction.original_response()
            await msg.add_reaction("👍")
            await msg.add_reaction("👎")
            await self.message.delete()
        except:
            pass
