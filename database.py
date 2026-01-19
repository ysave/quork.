import asyncio
import asyncpg
from config import DATABASE_URL


async def create_pool(max_retries: int = 5, retry_delay: int = 3) -> asyncpg.Pool | None:
    """Create and return a database connection pool with retry logic."""
    if not DATABASE_URL:
        print("Warning: DATABASE_URL not set. Quote commands will not work.")
        return None

    for attempt in range(max_retries):
        try:
            pool = await asyncpg.create_pool(DATABASE_URL)
            print("Database connection established.")
            return pool
        except Exception as e:
            print(f"Database connection attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                print(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)

    print("Warning: Could not connect to database after all retries.")
    print("Bot will start, but quote commands will not work until database is available.")
    return None


async def setup_tables(pool: asyncpg.Pool) -> None:
    """Create database tables if they don't exist."""
    async with pool.acquire() as conn:
        # Quotes table
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS quotes (
          id           BIGSERIAL PRIMARY KEY,
          guild_id     BIGINT NOT NULL,
          author_name  TEXT,
          quote_text   TEXT NOT NULL,
          context      TEXT,
          added_by_id  BIGINT,
          created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)

        # Add context column if it doesn't exist (migration for existing databases)
        await conn.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name = 'quotes' AND column_name = 'context') THEN
                ALTER TABLE quotes ADD COLUMN context TEXT;
            END IF;
        END $$;
        """)
        
        # Remove duplicates before adding unique constraint
        await conn.execute("""
            DELETE FROM quotes a USING quotes b
            WHERE a.id > b.id
            AND a.guild_id = b.guild_id
            AND a.quote_text = b.quote_text;
        """)

        # Ensure unique quotes per guild
        # We use an index on the MD5 hash of the text if it's very long, but for simplicity
        # and strictness, let's try a direct unique constraint.
        # However, to be safe with long text, we can use a unique index on the text content.
        # If the text is huge, this might be an issue, but usually quotes fit in a page.
        await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS quotes_guild_text_idx ON quotes (guild_id, quote_text);
        """)

        # Permissions table
        # permission types: 'edit_all', 'remove_all'
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS permissions (
          id           BIGSERIAL PRIMARY KEY,
          guild_id     BIGINT NOT NULL,
          user_id      BIGINT NOT NULL,
          permission   TEXT NOT NULL,
          granted_by   BIGINT,
          created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          UNIQUE(guild_id, user_id, permission)
        );
        """)

        # Votes table
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS quote_votes (
            quote_id    BIGINT NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
            user_id     BIGINT NOT NULL,
            vote        SMALLINT NOT NULL CHECK (vote IN (1, -1)),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (quote_id, user_id)
        );
        """)

    print("Database tables verified.")
