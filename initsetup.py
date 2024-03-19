import os
from flashbdev import bdev


def check_bootsec():
    buf = bytearray(bdev.ioctl(5, 0))  # 5 is SEC_SIZE
    bdev.readblocks(0, buf)
    empty = True
    for b in buf:
        if b != 0xFF:
            empty = False
            break
    if empty:
        return True
    fs_corrupted()


def fs_corrupted():
    import time
    import micropython

    # Allow this loop to be stopped via Ctrl-C.
    micropython.kbd_intr(3)

    while 1:
        print(
            """\
The filesystem appears to be corrupted. If you had important data there, you
may want to make a flash snapshot to try to recover it. Otherwise, perform
factory reprogramming of MicroPython firmware (completely erase flash, followed
by firmware programming).
"""
        )
        time.sleep(3)


def setup():
    check_bootsec()
    print("Performing initial setup")
    if bdev.info()[4] == "vfs":
        os.VfsLfs2.mkfs(bdev)
        vfs = os.VfsLfs2(bdev)
    elif bdev.info()[4] == "ffat":
        os.VfsFat.mkfs(bdev)
        vfs = os.VfsFat(bdev)
    os.mount(vfs, "/")
    with open("boot.py", "w") as f:
        f.write(
            """\
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
"""
        )
    return vfs