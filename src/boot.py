import gc
import time
import asyncio
print("Extract app to flash")
extart_start = time.time()
import frozen_app
print(f"Finished in {time.time()-extart_start}sec")

from lib.servo42c import *
from config.pin_config import *


if __name__ == '__main__':
    gc.collect()
    print('Start')
    import connect_wifi
    import web

    loop = asyncio.get_event_loop()
    loop.run_forever()

