import asyncio
from functools import wraps
import discord
from config import EPHEMERAL_DELETE_DELAY


# --- Ephemeral message helpers ---

async def delete_after_delay(interaction: discord.Interaction, delay: float = EPHEMERAL_DELETE_DELAY):
    """Delete an ephemeral message after a delay."""
    await asyncio.sleep(delay)
    try:
        await interaction.delete_original_response()
    except:
        pass


async def send_ephemeral_temp(interaction: discord.Interaction, **kwargs):
    """Send an ephemeral message that auto-deletes after a short time."""
    kwargs['ephemeral'] = True
    if interaction.response.is_done():
        await interaction.followup.send(**kwargs)
    else:
        await interaction.response.send_message(**kwargs)
    asyncio.create_task(delete_after_delay(interaction))


async def send_error(interaction: discord.Interaction, message: str, title: str = "Error"):
    """Send a temporary error message."""
    embed = discord.Embed(title=title, description=message, color=discord.Color.red())
    await send_ephemeral_temp(interaction, embed=embed)


# --- Command decorators ---

def guild_only(func):
    """Decorator to ensure command is run in a guild."""
    @wraps(func)
    async def wrapper(interaction: discord.Interaction, *args, **kwargs):
        if not interaction.guild_id:
            return await send_error(interaction, "This command only works in servers.")
        return await func(interaction, *args, **kwargs)
    return wrapper


def requires_db(bot):
    """Decorator to ensure database is available."""
    def decorator(func):
        @wraps(func)
        async def wrapper(interaction: discord.Interaction, *args, **kwargs):
            if not bot.pool:
                return await send_error(interaction, "Database not available. Please try again later.", "Database Error")
            return await func(interaction, *args, **kwargs)
        return wrapper
    return decorator


# --- User info helpers ---

async def get_user_display_info(bot, guild, user_id: int) -> tuple[str, str | None]:
    """Get a user's display name and avatar URL."""
    creator = None
    if guild:
        creator = guild.get_member(user_id)
    if not creator:
        creator = bot.get_user(user_id)
    if not creator:
        try:
            creator = await bot.fetch_user(user_id)
        except:
            pass

    if not creator:
        return f"User {user_id}", None

    if isinstance(creator, discord.Member):
        return creator.display_name, creator.display_avatar.url if creator.display_avatar else None

    name = getattr(creator, 'global_name', None) or creator.name
    avatar = creator.avatar.url if creator.avatar else (creator.default_avatar.url if creator.default_avatar else None)
    return name, avatar


def format_date(dt) -> str:
    """Format a datetime object to a readable string."""
    return dt.strftime("%B %d, %Y") if hasattr(dt, 'strftime') else "Unknown date"


# --- Base paginated view ---

class PaginatedView(discord.ui.View):
    """Base class for paginated selection views."""

    def __init__(self, rows: list, user_id: int, items_per_page: int = 25, timeout: int = 300):
        super().__init__(timeout=timeout)
        self.rows = list(rows)
        self.user_id = user_id
        self.page = 0
        self.items_per_page = items_per_page
        self.message = None
        self._update_total_pages()

    def _update_total_pages(self):
        self.total_pages = max(1, (len(self.rows) + self.items_per_page - 1) // self.items_per_page)

    def get_page_rows(self):
        start = self.page * self.items_per_page
        return self.rows[start:start + self.items_per_page]

    def create_embed(self) -> discord.Embed:
        """Override this to create the embed for the current page."""
        raise NotImplementedError

    def get_select_placeholder(self) -> str:
        """Override this to set the select menu placeholder."""
        return "Choose an option..."

    async def on_select(self, interaction: discord.Interaction, quote_id: int):
        """Override this to handle selection."""
        raise NotImplementedError

    def update_view(self):
        self.clear_items()
        page_rows = self.get_page_rows()

        if page_rows:
            select = discord.ui.Select(placeholder=self.get_select_placeholder())
            for row in page_rows:
                text = row['quote_text']
                # Label shows quote text (max 100 chars), description shows author if available
                label = text[:97] + "..." if len(text) > 100 else text
                desc = f"~ {row['author_name']}" if row.get('author_name') else None
                select.add_option(
                    label=label,
                    description=desc,
                    value=str(row['id']),
                )
            select.callback = self._select_callback
            self.add_item(select)

        if self.total_pages > 1:
            prev_btn = discord.ui.Button(emoji="◀️", disabled=(self.page == 0))
            next_btn = discord.ui.Button(emoji="▶️", disabled=(self.page >= self.total_pages - 1))
            prev_btn.callback = self._prev_callback
            next_btn.callback = self._next_callback
            self.add_item(prev_btn)
            self.add_item(next_btn)

    async def _check_user(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await send_ephemeral_temp(interaction, content="This is not your selection!")
            return False
        return True

    async def _select_callback(self, interaction: discord.Interaction):
        if not await self._check_user(interaction):
            return
        quote_id = int(interaction.data['values'][0])
        await self.on_select(interaction, quote_id)

    async def _prev_callback(self, interaction: discord.Interaction):
        if not await self._check_user(interaction):
            return
        self.page = max(0, self.page - 1)
        self.update_view()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    async def _next_callback(self, interaction: discord.Interaction):
        if not await self._check_user(interaction):
            return
        self.page = min(self.total_pages - 1, self.page + 1)
        self.update_view()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except:
            pass
