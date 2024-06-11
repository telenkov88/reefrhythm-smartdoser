try:
    import uasyncio as asyncio
except ImportError:
    import asyncio
try:
    from utime import ticks_us, ticks_diff
except ImportError:
    from lib.mocks import ticks_us,ticks_diff


def timed_function(f):
    """Decorator to measure the execution time of a function in milliseconds."""
    def new_func(*args, **kwargs):
        myname = f.__name__
        t_start = ticks_us()
        result = f(*args, **kwargs)
        t_end = ticks_us()
        delta = ticks_diff(t_end, t_start)
        print('Function {} Time = {:6.3f}ms'.format(myname, delta / 1000))
        return result
    return new_func


def restart_on_failure(func):
    async def wrapper(*args, **kwargs):
        while True:
            try:
                await func(*args, **kwargs)
            except Exception as e:
                print(f"Error occurred: {e} in {func}")
            print(f"Restarting task {func.__name__} after 10sec delay...")
            await asyncio.sleep(10)
    return wrapper
