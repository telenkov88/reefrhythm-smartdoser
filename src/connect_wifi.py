import json
import time
import asyncio

import machine

try:
    import network
except ImportError:
    print("Only for Micropython")

from random import randint

try:
    with open("./config/settings.json", 'r') as settings_config:
        settings = json.load(settings_config)
        hostname = settings["hostname"] if "hostname" in settings else "doser"
        PUMP_NUM = settings["pump_number"] if "pump_number" in settings else 1
except OSError as e:
    print(e)
    hostname = "hostname"

except OSError as e:
    hostname = "doser"
    mdns = "doser"


nic = network.WLAN(network.STA_IF)
ap = network.WLAN(network.AP_IF)
ap.config(dhcp_hostname=hostname)
nic.config(dhcp_hostname=hostname)

from lib.microdot.microdot import Microdot, redirect, send_file

web_file_extension = ".gz"
web_compress = True


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

    @captive_portal.route('/styles/<path:path>')
    async def styles(request, path):
        if '..' in path:
            # directory traversal is not allowed
            return 'Not found', 404
        return send_file('static/styles/' + path, compressed=web_compress,
                         file_extension=web_file_extension)


    @captive_portal.route('/icon/<path:path>')
    async def static(request, path):
        if '..' in path:
            # directory traversal is not allowed
            return 'Not found', 404
        return send_file('static/icon/' + path)

    @captive_portal.route('/javascript/<path:path>')
    async def javascript(request, path):
        if '..' in path:
            # directory traversal is not allowed
            return 'Not found', 404
        return send_file('static/javascript/' + path, compressed=web_compress,
                         file_extension=web_file_extension)


    @captive_portal.route('/', methods=['GET', 'POST'])
    async def index(request):
        if request.method == 'GET':
            response = send_file('static/settings.html', compressed=web_compress,
                                 file_extension=web_file_extension)
            response.set_cookie('hostname', hostname)
            response.set_cookie(f'CaptivePortal', True)
            response.set_cookie(f'Mac', ap.config('mac'))
            if 'ssid' in globals():
                response.set_cookie('current_ssid', ssid)
            else:
                response.set_cookie('current_ssid', "")
            response.set_cookie(f'PumpNumber', json.dumps({"pump_num": PUMP_NUM}))
        else:
            new_ssid = request.json[f"ssid"]
            new_psw = request.json[f"psw"]
            new_hostname = request.json[f"hostname"]
            new_mdns = request.json[f"mdns"]
            if new_ssid and new_psw:
                with open("./config/wifi.json", "w") as f:
                    f.write(json.dumps({"ssid": new_ssid, "password": new_psw}))
            new_pump_num = request.json[f"pumpNum"]
            with open("./config/settings.json", "w") as f:
                f.write(json.dumps({"pump_number": new_pump_num,
                                    "hostname": new_hostname}))
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
