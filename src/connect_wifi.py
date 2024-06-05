try:
    import uasyncio as asyncio
    import network
    import lib.ntptime as ntptime
    import machine
except ImportError:
    import asyncio
    from lib.mocks import ntptime, network, machine
    import lib.mocks
from random import randint
import shared
import time


async def sync_time():
    ntptime.host = shared.settings["ntphost"]
    while not shared.wifi.isconnected():
        await asyncio.sleep(1)
    # Initial time sync is Mandatory to job scheduler
    while not shared.time_synced:
        i = 0
        try:
            print("Local time before synchronization：%s" % str(time.localtime()))
            ntptime.settime(shared.settings["timezone"])
            print("Local time after synchronization：%s" % str(time.localtime()))
            shared.time_synced = True
            break
        except Exception as _e:
            i += 1
            if i == 10:
                shared.wifi.active(False)
            elif i > 40:
                machine.reset()
            print("Failed to sync time on start. ", _e)
        await asyncio.sleep(10)

    while True:
        if shared.wifi.isconnected():
            x = 0
            while True:
                try:
                    print("Local time before synchronization：%s" % str(time.localtime()))
                    ntptime.settime(shared.settings["timezone"])
                    print("Local time after synchronization：%s" % str(time.localtime()))
                    shared.time_synced = True
                    break
                except Exception as _e:
                    x += 1
                    print(f'{x} time sync failed, Error: {_e}')
                if x >= 60:
                    print("Time sync not working, reboot")
                    machine.reset()

                await asyncio.sleep(60)
        else:
            print("wifi disconnected")

        await asyncio.sleep(1800)


async def reconnect_wifi(wifi, ssid, password, hostname):
    print(f"Try to connect wifi {ssid}")
    if wifi.isconnected():
        return
    try:
        print("Disconnect wifi")
        wifi.disconnect()
    except Exception as e:
        print(e)
    try:
        print("Disable Wifi")
        wifi.active(False)
    except Exception as e:
        print(e)
    await asyncio.sleep(2)
    try:
        print("Activate Wifi")
        wifi.active(True)
    except Exception as e:
        print("Failed to activate wifi, ", e)
    await asyncio.sleep(2)

    try:
        print(f"Set hostname: {hostname}.local")
        wifi.config(dhcp_hostname=hostname)
        print(f"Connect to ssid {ssid}")
        wifi.connect(ssid, password)
    except OSError as wifi_error:
        print(f"wi-fi {ssid} connection failed: ", wifi_error)
    await asyncio.sleep(20)


async def maintain_wifi(ssid, password, hostname):
    if not ssid:
        shared.wifi.active(False)
        await asyncio.sleep(1)
        ap_ssid = 'ReefRhythm_' + str(randint(1000, 10000))
        shared.ap.active(True)
        shared.ap.config(essid=ap_ssid, password='')
        print(f"Wifi AP ssid: {ap_ssid}")
    while not ssid:
        await asyncio.sleep(5)
    shared.ap.active(False)
    asyncio.run(reconnect_wifi(shared.wifi, ssid, password, hostname))

    retries = 0
    while True:
        if not shared.wifi.isconnected():
            print(f'ERROR: WIFI disconnected')
            asyncio.run(reconnect_wifi(shared.wifi, ssid, password, hostname))

            if retries == 30:
                print(f"Wifi disconnected >{retries}min, reboot")
                machine.reset()
        else:
            retries = 0
            print(">> WIFI - Connected")
            ip = shared.wifi.ifconfig()[0]
            print(f"http://{shared.settings['hostname']}.local")
            print(f"http://{ip}")
            print(f"http://{ip}/dose?direction=1&amount=2&duration=10")
            print(f"http://{ip}/run?direction=1&rpm=10&duration=10")

            await asyncio.sleep(60)


async def main():
    tasks = [
        asyncio.create_task(sync_time()),
        asyncio.create_task(maintain_wifi(shared.ssid, shared.password, shared.settings["hostname"]))
    ]
    await asyncio.gather(*tasks, return_exceptions=True)

if __name__ == "__main__":
    asyncio.run(main())
