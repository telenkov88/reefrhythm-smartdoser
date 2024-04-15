import json
import time
import asyncio

import machine

try:
    import network
except ImportError:
    print("Only for Micropython")

import sys
from random import randint
nic = network.WLAN(network.STA_IF)
ap = network.WLAN(network.AP_IF)
from lib.microdot.microdot import Microdot, redirect, send_file


try:
    with open("./config/wifi.json", 'r') as wifi_config:
        wifi_settings = json.load(wifi_config)
        ssid = wifi_settings["ssid"]
        password = wifi_settings["password"]
    ap.active(False)
except OSError as e:
    print(e)
    print("Wifi network are not defined, starting AP mode")
    ap.active(False)
    nic.active(False)
    ap_ssid = 'ReefRhythm_' + str(randint(1000, 10000))
    print(f"Wifi ssid: {ap_ssid}")
    ap.active(True)
    ap.config(essid=ap_ssid, password='')

    while not ap.active():
        pass

    print('Connection successful')
    print(ap.ifconfig())

    captive_portal = Microdot()

    @captive_portal.route('/', methods=['GET', 'POST'])
    async def index(request):
        print("Got connection")
        if request.method == 'GET':
            response = send_file('static/settings.html')
            if 'ssid' in globals():
                response.set_cookie(f'current_ssid', ssid)
            else:
                response.set_cookie(f'current_ssid', "")

        else:
            new_ssid = request.json[f"ssid"]
            new_psw = request.json[f"psw"]
            with open("./config/wifi.json", "w") as f:
                f.write(json.dumps({"ssid": new_ssid, "password": new_psw}))
            print(f"Setting up new wifi {new_ssid}, Reboot...")
            machine.reset()
        return response

    print("Start captive portal")
    captive_portal.run(port=80)

print(f"Connectiong to {ssid}")
try:
    nic.active(True)
    nic.connect(ssid, password)
except Exception as e:
    print(f"Failed to connect to wifi {e}")


async def maintain_wifi(wifi):
    await asyncio.sleep(5)
    while True:
        if not wifi.isconnected():
            print(f'ERROR: WIFI disconnected')
            wifi.active(True)
            print("set wifi Active")
            try:
                wifi.connect(ssid, password)
            except OSError as wifi_error:
                print(f"wi-fi {ssid} connection failed: ", wifi_error)
            print(f"Try to connect wifi {ssid}")
            await asyncio.sleep(60)

            retries = 0
            while not wifi.isconnected():

                print(f'Wifi disconnected for {retries}min')
                print("Try to restart wifi")
                wifi.disconnect()
                wifi.active(False)
                await asyncio.sleep(5)
                print(f"Activate wifi, SSID: {ssid}")
                wifi.active(True)
                wifi.connect(ssid, password)
                await asyncio.sleep(120)
                retries = retries + 1

                if retries == 30:
                    print(f"Wifi disconnected >{retries}min, reboot")
                    machine.reset()
        else:
            print(">> WIFI - Connected")
            ip = nic.ifconfig()[0]
            print(f"http://{ip}")
            print(f"http://{ip}/dose?direction=1&volume=2&time=10")
            print(f"http://{ip}/run_with_rpm?direction=1&rpm=10&time=10")

            await asyncio.sleep(240)


def wait_connection(nic):
    count = 0
    while not nic.isconnected():
        print("wait")
        count += 1
        if count >= 40:
            raise OSError("Failed to connecto to wifi")
        time.sleep(1)


asyncio.create_task(maintain_wifi(nic))
