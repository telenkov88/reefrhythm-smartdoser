try:
    import uasyncio as asyncio
except ImportError:
    import asyncio


def restart_on_failure(func):
    async def wrapper(*args, **kwargs):
        while True:
            try:
                await func(*args, **kwargs)
            except Exception as e:
                print(f"Exception occurred: {e}")
            print("Restarting task after 10sec delay...")
            await asyncio.sleep(10)
    return wrapper
