from aiohttp import web
import asyncpg

from config import API_HOST, API_PORT


def create_api_app(pool: asyncpg.Pool) -> web.Application:
    """Create and configure the API application."""
    app = web.Application(middlewares=[cors_middleware])
    app['pool'] = pool

    app.router.add_get('/api/quotes', get_quotes)

    return app

@web.middleware
async def cors_middleware(request, handler):
    # If OPTIONS request (preflight), return quick with headers
    if request.method == "OPTIONS":
        response = web.Response()
    else:
        # Process normal request
        response = await handler(request)

    # Add CORS headers to response
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Max-Age'] = '3600'

    return response


async def get_quotes(request: web.Request) -> web.Response:
    """Get all quotes, optionally filtered by guild_id."""
    pool = request.app['pool']
    guild_id = request.query.get('guild_id')

    try:
        async with pool.acquire() as conn:
            if guild_id:
                rows = await conn.fetch(
                    """SELECT q.id, q.guild_id, q.author_name, q.quote_text, q.context, q.added_by_id, q.created_at,
                              COALESCE(SUM(v.vote), 0)::INT AS votes
                       FROM quotes q
                       LEFT JOIN quote_votes v ON v.quote_id = q.id
                       WHERE q.guild_id = $1
                       GROUP BY q.id
                       ORDER BY q.created_at DESC""",
                    int(guild_id)
                )
            else:
                rows = await conn.fetch(
                    """SELECT q.id, q.guild_id, q.author_name, q.quote_text, q.context, q.added_by_id, q.created_at,
                              COALESCE(SUM(v.vote), 0)::INT AS votes
                       FROM quotes q
                       LEFT JOIN quote_votes v ON v.quote_id = q.id
                       GROUP BY q.id
                       ORDER BY q.created_at DESC"""
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
                'votes': row['votes'],
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
