#!/usr/bin/env python3
"""Fixed TCP forwarding for loopback-only access to the isolated local stack."""

from __future__ import annotations

import asyncio


ROUTES = ((18000, "api", 8000), (13000, "web", 3000))


async def _copy(source: asyncio.StreamReader, target: asyncio.StreamWriter) -> None:
    while data := await source.read(64 * 1024):
        target.write(data)
        await target.drain()


async def _forward(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    target_host: str,
    target_port: int,
) -> None:
    upstream_writer: asyncio.StreamWriter | None = None
    try:
        upstream_reader, upstream_writer = await asyncio.wait_for(
            asyncio.open_connection(target_host, target_port), timeout=5
        )
        tasks = {
            asyncio.create_task(_copy(client_reader, upstream_writer)),
            asyncio.create_task(_copy(upstream_reader, client_writer)),
        }
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*done, *pending, return_exceptions=True)
    except (OSError, TimeoutError):
        pass
    finally:
        client_writer.close()
        if upstream_writer is not None:
            upstream_writer.close()
            await upstream_writer.wait_closed()
        await client_writer.wait_closed()


async def main() -> None:
    servers = []
    for local_port, target_host, target_port in ROUTES:
        servers.append(await asyncio.start_server(
            lambda reader, writer, host=target_host, port=target_port: _forward(
                reader, writer, host, port
            ),
            host="0.0.0.0",
            port=local_port,
            limit=64 * 1024,
        ))
    async with servers[0], servers[1]:
        await asyncio.gather(*(server.serve_forever() for server in servers))


if __name__ == "__main__":
    asyncio.run(main())
