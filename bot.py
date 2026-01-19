import asyncpg
import discord

from config import TOKEN, DATABASE_URL, API_ENABLED
from database import create_pool, setup_tables
from commands.quotes import setup_quote_commands
from commands.help import setup_help_command
from commands.moderation import setup_moderation_commands
from api import start_api_server

INTENTS = discord.Intents.default()
INTENTS.reactions = True
INTENTS.members = True  # Enable in Discord Developer Portal if needed


class DiscordBot(discord.Client):
    def __init__(self):
        super().__init__(intents=INTENTS)
        self.tree = discord.app_commands.CommandTree(self)
        self.pool: asyncpg.Pool | None = None
        self.api_runner = None

    async def close(self):
        if self.api_runner:
            await self.api_runner.cleanup()
        if self.pool:
            await self.pool.close()
        await super().close()

    async def setup_hook(self):
        # Database
        self.pool = await create_pool()
        if self.pool:
            await setup_tables(self.pool)

            # Start API server if enabled
            if API_ENABLED:
                try:
                    self.api_runner = await start_api_server(self.pool)
                except Exception as e:
                    print(f"Failed to start API server: {e}")

        # Commands - add new command modules here
        setup_quote_commands(self)
        setup_moderation_commands(self)
        setup_help_command(self)

        # Sync
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} command(s).")
        except Exception as e:
            print(f"Error syncing commands: {e}")


bot = DiscordBot()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    print(f"Ready! Connected to {len(bot.guilds)} guild(s).")


@bot.event
async def on_error(event, *args, **kwargs):
    import traceback
    print(f"Error in {event}:")
    traceback.print_exc()


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN not set")

    if not DATABASE_URL:
        print("Warning: DATABASE_URL not set. Quote commands won't work.")

    try:
        bot.run(TOKEN)
    except KeyboardInterrupt:
        print("Bot stopped.")
    except Exception as e:
        import traceback
        print(f"Fatal: {e}")
        traceback.print_exc()
