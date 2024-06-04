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
            print("Adding command to buffer")
            self.buffer.append((func, callback, args, kwargs))
            print(f"Buffer length after adding: {len(self.buffer)}")
            if len(self.buffer) == 1:
                asyncio.create_task(self.process_commands())

    async def process_commands(self):
        while self.buffer:
            print("Attempting to process commands")
            async with self.lock:
                if not self.buffer:
                    print("Buffer was empty when trying to process")
                    return
                func, callback, args, kwargs = self.buffer.pop(0)
            try:
                print("Processing a command")
                result = await func(*args, **kwargs)
                if callback:
                    callback(result)
            except Exception as e:
                print("Process command exception: ", e)
            print("Command processed, current buffer length: ", len(self.buffer))



