import asyncio
import os
import pty
import select
import struct
import fcntl
import termios
from typing import AsyncGenerator


class TerminalSession:
    def __init__(self, cols: int = 80, rows: int = 24):
        self.cols = cols
        self.rows = rows
        self.pid: int | None = None
        self.master_fd: int | None = None

    def start(self, cwd: str | None = None) -> None:
        pid, master_fd = pty.fork()
        if pid == 0:
            os.chdir(cwd or os.path.expanduser("~"))
            os.environ["TERM"] = "xterm-256color"
            os.execvp("bash", ["bash", "-l"])
        else:
            self.pid = pid
            self.master_fd = master_fd
            self._set_size(self.cols, self.rows)

    def _set_size(self, cols: int, rows: int) -> None:
        if self.master_fd is None:
            return
        self.cols = cols
        self.rows = rows
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)

    def resize(self, cols: int, rows: int) -> None:
        self._set_size(cols, rows)

    def write(self, data: str) -> None:
        if self.master_fd is not None:
            os.write(self.master_fd, data.encode("utf-8", errors="replace"))

    async def read_output(self) -> AsyncGenerator[str, None]:
        if self.master_fd is None:
            return
        loop = asyncio.get_event_loop()
        while True:
            if self.pid is not None:
                try:
                    pid, status = os.waitpid(self.pid, os.WNOHANG)
                    if pid != 0 and os.WIFEXITED(status):
                        break
                except ChildProcessError:
                    break
            ready, _, _ = await loop.run_in_executor(
                None, lambda: select.select([self.master_fd], [], [], 0.1)
            )
            if ready:
                try:
                    data = os.read(self.master_fd, 4096)
                    if not data:
                        break
                    yield data.decode("utf-8", errors="replace")
                except OSError:
                    break
            await asyncio.sleep(0.01)

    def close(self) -> None:
        if self.pid is not None:
            try:
                os.kill(self.pid, 15)
            except Exception:
                pass
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except Exception:
                pass
