import asyncio
from typing import Awaitable, Callable

LogCallback = Callable[[str], Awaitable[None] | None]

_subscribers: set[LogCallback] = set()
_extra_handlers: list[Callable[[str], Awaitable[None]]] = []


def subscribe(callback: LogCallback) -> None:
    _subscribers.add(callback)


def unsubscribe(callback: LogCallback) -> None:
    _subscribers.discard(callback)


def add_handler(handler: Callable[[str], Awaitable[None]]) -> None:
    _extra_handlers.append(handler)


async def emit(line: str) -> None:
    for cb in list(_subscribers):
        try:
            result = cb(line)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            pass
    for handler in _extra_handlers:
        try:
            await handler(line)
        except Exception:
            pass
