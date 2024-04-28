try:
    import uasyncio as asyncio
    import network
except ImportError:
    import asyncio
    from unittest.mock import MagicMock, Mock
    network = Mock()
    network.AP_IF = Mock()
from random import randint


async def reconnect_wifi(wifi, ssid, password):
    print(f"Try to connect wifi {ssid}")
    if wifi.isconnected():
        return
    try:
        wifi.disconnect()
    except Exception as e:
        print(e)
    try:
        wifi.active(False)
    except Exception as e:
        print(e)
    await asyncio.sleep(5)
    wifi.active(True)
    await asyncio.sleep(5)
    try:
        wifi.connect(ssid, password)
    except OSError as wifi_error:
        print(f"wi-fi {ssid} connection failed: ", wifi_error)
    await asyncio.sleep(20)


async def maintain_wifi(ssid, password):
    ap = network.WLAN(network.AP_IF)
    wifi = network.WLAN(network.STA_IF)

    if not ssid:
        wifi.active(False)
        await asyncio.sleep(1)
        ap_ssid = 'ReefRhythm_' + str(randint(1000, 10000))
        ap.active(True)
        ap.config(essid=ap_ssid, password='')
        print(f"Wifi AP ssid: {ap_ssid}")
    while not ssid:
        await asyncio.sleep(5)
    ap.active(False)
    asyncio.run(reconnect_wifi(wifi, ssid, password))

    retries = 0
    while True:
        if not wifi.isconnected():
            print(f'ERROR: WIFI disconnected')
            asyncio.run(reconnect_wifi(wifi, ssid, password))

            if retries == 30:
                print(f"Wifi disconnected >{retries}min, reboot")
                machine.reset()
            wifi_connected = False
        else:
            wifi_connected = True
            retries = 0
            print(">> WIFI - Connected")
            ip = wifi.ifconfig()[0]
            print(f"http://{ip}")
            print(f"http://{ip}/dose?direction=1&volume=2&time=10")
            print(f"http://{ip}/run_with_rpm?direction=1&rpm=10&time=10")

            await asyncio.sleep(60)


if __name__ == "__main__":
    print("Disconnect AP")
    from load_configs import *
    ap = network.WLAN(network.AP_IF)
    ap.active(False)
    wifi = network.WLAN(network.STA_IF)
    asyncio.run(maintain_wifi(ssid, password))
