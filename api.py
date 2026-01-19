from aiohttp import web
import asyncpg

from config import API_HOST, API_PORT


def create_api_app(pool: asyncpg.Pool) -> web.Application:
    """Create and configure the API application."""
    app = web.Application()
    app['pool'] = pool

    app.router.add_get('/api/quotes', get_quotes)

    return app


async def get_quotes(request: web.Request) -> web.Response:
    """Get all quotes, optionally filtered by guild_id."""
    pool = request.app['pool']
    guild_id = request.query.get('guild_id')

    try:
        async with pool.acquire() as conn:
            if guild_id:
                rows = await conn.fetch(
                    """SELECT id, guild_id, author_name, quote_text, context, added_by_id, created_at
                       FROM quotes WHERE guild_id = $1 ORDER BY created_at DESC""",
                    int(guild_id)
                )
            else:
                rows = await conn.fetch(
                    """SELECT id, guild_id, author_name, quote_text, context, added_by_id, created_at
                       FROM quotes ORDER BY created_at DESC"""
                )

        quotes = [
            {
                'id': row['id'],
                'guild_id': str(row['guild_id']),
                'author_name': row['author_name'],
                'quote_text': row['quote_text'],
                'context': row['context'],
                'added_by_id': str(row['added_by_id']) if row['added_by_id'] else None,
                'created_at': row['created_at'].isoformat() if row['created_at'] else None,
            }
            for row in rows
        ]

        return web.json_response({'quotes': quotes, 'count': len(quotes)})
    except ValueError:
        return web.json_response({'error': 'Invalid guild_id'}, status=400)
    except Exception as e:
        print(f"API error in get_quotes: {e}")
        return web.json_response({'error': 'Internal server error'}, status=500)


async def start_api_server(pool: asyncpg.Pool) -> web.AppRunner:
    """Start the API server and return the runner."""
    app = create_api_app(pool)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, API_HOST, API_PORT)
    await site.start()
    print(f"API server started on http://{API_HOST}:{API_PORT}")
    return runner
