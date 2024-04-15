try:
    import uasyncio as asyncio
    from ulab import numpy as np
except ImportError:
    import numpy as np
    np.float = np.float32
    import asyncio as asyncio


# Implementation of missed asyncio.Future
class CustomFuture:
    def __init__(self):
        self._result = None
        self._event = asyncio.Event()

    def set_result(self, result):
        self._result = result
        self._event.set()

    async def wait(self):
        await self._event.wait()
        return self._result


class CommandBuffer:
    def __init__(self):
        self.buffer = []
        self.lock = asyncio.Lock()

    async def add_command(self, func, callback, *args, **kwargs):
        async with self.lock:
            self.buffer.append((func, callback, args, kwargs))
            if len(self.buffer) == 1:
                await self.process_commands()

    async def process_commands(self):
        while self.buffer:
            func, callback, args, kwargs = self.buffer[0]
            result = await func(*args, **kwargs)
            if callback:
                callback(result)
            print("remove task from buffer")
            del self.buffer[0]


class TaskManager:
    def __init__(self, cmd_buffer):
        super().__init__()
        self.tasks = {}
        self.cmd_buffer = cmd_buffer

    async def add_task(self, coro, name):
        """Add a new task."""
        task = asyncio.create_task(coro)
        self.tasks[name] = task
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Task {name} encountered an error: {e}")
        finally:
            self.tasks.pop(name, None)

    def cancel_task(self, name):
        """Cancel a specific task by name."""
        task = self.tasks.get(name)
        if task:
            task.cancel()
            print(f"Task {name} has been cancelled.")
        else:
            print(f"No task with name {name} found.")

    def cancel_all_tasks(self):
        """Cancel all tasks."""
        for task in self.tasks.values():
            task.cancel()
        print("All tasks have been cancelled.")
