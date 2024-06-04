import shared
import machine
from connect_wifi import sync_time
from lib.mqtt_worker import *
from lib.microdot.microdot import Microdot, redirect, send_file
from lib.microdot.sse import with_sse
import re
from lib.exec_code import evaluate_expression
from machine import Timer
from lib.decorator import restart_on_failure
import requests
import time
from lib.pump_control import stepper_run, analog_control_worker
from lib.stepper_doser_math import linear_interpolation, extrapolate_flow_rate
from config.pin_config import *
import array

try:
    # Import 3-part Add-ons
    import extension

    addon = True
except ImportError as extension_error:
    print("Failed to import extension, ", extension_error)
    addon = False

import binascii

try:
    import lib.ntptime as ntptime
    import lib.mcron as mcron
    import uasyncio as asyncio
    import gc
    import ota.status
    import ota.update
    import ota.rollback
    from machine import UART, Pin, ADC, unique_id
    from ulab import numpy as np
    from release_tag import *
    from lib.umqtt.robust2 import MQTTClient

    mqtt_client = MQTTClient(f"ReefRhythm-{unique_id}", shared.mqtt_settings["broker"], keepalive=40, socket_timeout=2)

    USE_RAM = False

except ImportError:
    import asyncio
    import numpy as np
    from lib.mocks import *

    mqtt_client = MQTTClient()
    import os

    os.system("python ../scripts/compress_web.py --path ./")
    USE_RAM = False

if USE_RAM:
    print("\nload html to memory")
    # Usage example
    filenames = ['calibration.html', 'doser.html', 'ota-upgrade.html', 'settings.html',
                 'settings-captive.html']  # List your .html.gz files here
    html_files = shared.load_files_to_ram('static/', filenames, f'{shared.web_file_extension}')
    for file in html_files:
        print(file)
else:
    html_files = []

if USE_RAM:
    print("\nload javascripts to memory")
    filenames = ['bootstrap.bundle.min.js', 'chart.min.js']
    js_files = shared.load_files_to_ram('static/javascript/', filenames, f'{shared.web_file_extension}')
else:
    js_files = []

for file in js_files:
    print(file)

if USE_RAM:
    print("\nload css to memory")
    filenames = ['cerulean/bootstrap.min.css',
                 'cyborg/bootstrap.min.css',
                 'darkly/bootstrap.min.css',
                 'minty/bootstrap.min.css',
                 'pulse/bootstrap.min.css',
                 'united/bootstrap.min.css',
                 'vapor/bootstrap.min.css']
    css_files = shared.load_files_to_ram('static/styles', filenames, f'{shared.web_file_extension}')
else:
    css_files = []

for file in css_files:
    print(file)

app = Microdot()
gc.collect()
ota_progress = 0
firmware_size = None
firmware_link = "http://github.com/telenkov88/reefrhythm-smartdoser/releases/download/latest/micropython.bin"

should_continue = True  # Flag for shutdown
c = 0
mcron.init_timer()
mcron_keys = []

byte_string = shared.wifi.config('mac')
print(byte_string)
hex_string = binascii.hexlify(byte_string).decode('utf-8')
mac_address = ':'.join(hex_string[i:i + 2] for i in range(0, len(hex_string), 2)).upper()


# Define the maximum value for a 32-bit unsigned integer
UINT32_MAX = 4294967295

# Initialize the uptime counter
uptime_counter = 0


# Function to increment the uptime counter
def increment_uptime_counter(step=10):
    global uptime_counter
    if uptime_counter > UINT32_MAX - step:
        uptime_counter = (uptime_counter + step) - (UINT32_MAX + 1)
    else:
        uptime_counter += step
    print(f"uptime {uptime_counter} seconds")
    shared.mqtt_worker.add_message_to_publish("uptime", f"{uptime_counter} seconds")
    shared.mqtt_worker.add_message_to_publish("free_mem ", json.dumps({"free_mem": gc.mem_free() // 1024}))


# Set up a timer to call increment_uptime_counter every 10 seconds
timer = Timer(0)
timer.init(period=10 * 1000, mode=Timer.PERIODIC, callback=lambda t: increment_uptime_counter())


@micropython.native
async def adc_sampling():
    sampling_size = 5
    sampling_delay = 1 / sampling_size
    shared.adc_dict = {}

    adc_buffer = {}
    for _ in analog_pins:
        adc_buffer[_] = array.array('I', (0 for _ in range(sampling_size)))
        Pin(_, mode=Pin.IN, pull=Pin.PULL_UP)

    while True:
        for _ in range(sampling_size):
            for pin in analog_pins:
                adc_buffer[pin][_] = ADC(Pin(pin)).read()
            await asyncio.sleep(sampling_delay)
        for pin in analog_pins:
            shared.adc_dict[pin] = sum(adc_buffer[pin]) // sampling_size
        shared.adc_sampler_started = True


async def download_file_async(url, filename, progress=False):
    print("Start downloading ", url)
    global ota_progress
    response = requests.get(url, stream=True)

    # Check if the response indeed has a 'iter_content' method or equivalent
    if not hasattr(response.raw, 'read'):
        raise AttributeError("Response object doesn't support chunked reading.")

    chunk_size = 4096
    i = 0
    with open(filename, 'wb') as file:
        while True:
            chunk = response.raw.read(chunk_size)
            if not chunk:
                break
            file.write(chunk)
            await asyncio.sleep(0.1)  # Yield execution to other tasks
            if progress:
                ota_progress = i
            i += 1
    response.close()


@app.before_request
async def start_timer(request):
    request.g.start_time = time.time()


@app.after_request
async def end_timer(request, response):
    duration = time.time() - request.g.start_time
    print(f'Request took {duration:0.2f} seconds')


@app.route('/get_rpm_points')
async def get_rpm_points(request):
    pump_number = request.args.get('pump', default=1, type=int)
    print(f"return RPM points for pump{pump_number}")
    points = shared.chart_points[f"pump{pump_number}"][0].tolist()
    return json.dumps(points)


@app.route('/get_flow_points')
async def get_flow_points(request):
    pump_number = request.args.get('pump', default=1, type=int)
    print(f"return flow points for pump{pump_number}")
    points = shared.chart_points[f"pump{pump_number}"][1].tolist()
    print(points)
    return json.dumps(points)


@app.route('/get_analog_chart_points')
async def get_analog_chart_points(request):
    pump_number = request.args.get('pump', default=1, type=int)
    print(f"return analog input points for pump{pump_number}")
    points = shared.analog_chart_points[f"pump{pump_number}"]
    print(points)
    return json.dumps(points)


@app.route('/memfree')
async def get_free_mem(request):
    ret = gc.mem_free() // 1024
    print(f"free mem: {ret}Kb")
    return {"free_mem": ret}


@app.route('/favicon/<path:path>')
async def favicon(request, path):
    if '..' in path:
        # directory traversal is not allowed
        return 'Not found', 404
    print(f"sending static/favicon/{path}")
    return send_file('static/favicon/' + path)


@app.route('/site.webmanifest')
async def manifest(request):
    response = send_file('static/favicon/site.webmanifest')
    return response


@app.route('/styles/<path:path>')
async def styles(request, path):
    if '..' in path:
        # directory traversal is not allowed
        return 'Not found', 404

    if path in css_files:
        print(f"send css {path} from RAM")
        return send_file(path, compressed=shared.web_compress,
                         file_extension=shared.web_file_extension, stream=css_files[path])
    return send_file('static/styles/' + path, compressed=shared.web_compress,
                     file_extension=shared.web_file_extension)


@app.route('/javascript/<path:path>')
async def javascript(request, path):
    if '..' in path:
        # directory traversal is not allowed
        return 'Not found', 404
    print(f"Send file static/javascript/{path}")
    if path in js_files:
        print(f"send js {path} from RAM")
        return send_file(path, compressed=shared.web_compress,
                         file_extension=shared.web_file_extension, stream=js_files[path])
    else:
        print(f"send js {path} from DISK")
        return send_file('static/javascript/' + path, compressed=shared.web_compress,
                         file_extension=shared.web_file_extension)


@app.route('/static/<path:path>')
async def static(request, path):
    if '..' in path:
        # directory traversal is not allowed
        return 'Not found', 404
    return send_file('static/' + path)


@app.route('/icon/<path:path>')
async def static(request, path):
    if '..' in path:
        # directory traversal is not allowed
        return 'Not found', 404
    return send_file('static/icon/' + path)


@app.route('/icon/<path:path>')
async def static(request, path):
    if '..' in path:
        # directory traversal is not allowed
        return 'Not found', 404
    return send_file('static/icon/' + path)


@app.route('/dose', methods=['GET'])
async def dose(request):
    pump_id = request.args.get('id', default=1, type=int)
    amount = request.args.get('amount', default=0, type=float)
    duration = request.args.get('duration', default=0, type=float)
    direction = request.args.get('direction', default=1, type=int)
    print(f"[Pump{pump_id}] Dose {amount}ml in {duration}s ")
    task = asyncio.create_task(
        shared.command_handler.dose({"id": pump_id, "amount": amount, "duration": duration, "direction": direction}))
    print(">>>>>>>>>")
    await asyncio.sleep(1)
    return f"Initiated dosing task for Pump{pump_id}", 202


@app.route('/run', methods=['GET'])
async def run_with_rpm(request):
    pump_id = request.args.get('id', default=1, type=int)
    rpm = request.args.get('rpm', default=1, type=float)
    direction = request.args.get('direction', default=1, type=int)
    duration = request.args.get('duration', default=1, type=float)

    print(f"[Pump{pump_id}] Run {rpm}RPM for {duration}sec Dir={direction}")
    asyncio.create_task(
        shared.command_handler.run({"id": pump_id, "rpm": rpm, "duration": duration, "direction": direction}))


@app.route('/stop', methods=['GET'])
async def stop(request):
    pump_id = request.args.get('id', default=1, type=int)

    print(f"[Pump{pump_id}] Stop")
    asyncio.create_task(shared.command_handler.stop({"id": pump_id}))


@app.route('/refill', methods=['GET'])
async def refill(request):
    pump_id = request.args.get('id', default=1, type=int)
    _new_storage = request.args.get('storage', default=-1, type=int)
    print(f"[Pump{pump_id}] refill")
    if _new_storage < 0:
        asyncio.create_task(shared.command_handler.refill({"id": pump_id}))
    else:
        asyncio.create_task(shared.command_handler.refill({"id": pump_id, "storage": _new_storage}))


@app.route('/', methods=['GET', 'POST'])
async def index(request):
    if request.method == 'GET':
        # Captive portal
        if not shared.ssid:
            return setting_responce(request)

        if "doser.html" in html_files:
            print("Send doser.html.gz from RAM")
            response = send_file("doser.html", compressed=shared.web_compress,
                                 file_extension=shared.web_file_extension, stream=html_files["doser.html"])
        else:
            response = send_file('./static/doser.html', compressed=shared.web_compress,
                                 file_extension=shared.web_file_extension)

        response.set_cookie(f'AnalogPins', json.dumps(analog_pins))
        response.set_cookie(f'PumpNumber', json.dumps({"pump_num": shared.PUMP_NUM}))
        response.set_cookie(f'timeformat', shared.settings["timeformat"])
        response.set_cookie("pumpNames", json.dumps({"pumpNames": shared.settings["names"]}))
        response.set_cookie("color", shared.settings["color"])
        response.set_cookie("theme", shared.settings["theme"])

        if addon and hasattr(extension, 'extension_navbar'):
            response.set_cookie("Extension", json.dumps(extension.extension_navbar))

        return response
    else:
        # Captive portal
        if not shared.wifi_settings["ssid"]:
            return setting_process_post(request)

        response = redirect('/')
        data = request.json
        print(data)
        for _ in range(1, shared.PUMP_NUM + 1):
            if f"pump{_}" in data:
                if len(data[f"pump{_}"]["points"]) >= 2:
                    # response.set_cookie(f'AnalogInputDataPump{_}', json.dumps(data[f"pump{_}"]))

                    points = [(d['analogInput'], d['flowRate']) for d in data[f"pump{_}"]["points"]]
                    shared.analog_chart_points[f"pump{_}"] = linear_interpolation(points)
                    print(shared.analog_chart_points[f"pump{_}"])
                    # Save new settings
                    shared.analog_settings[f"pump{_}"] = data[f"pump{_}"]
                    shared.analog_en[_ - 1] = shared.analog_settings[f"pump{_}"]["enable"]

                else:
                    print(f"Pump{_} Not enough Analog Input points")
        with open("config/analog_settings.json", 'w') as write_file:
            write_file.write(json.dumps(shared.analog_settings))
        return response


@app.route('/time')
@with_sse
async def dose_ssetime(request, sse):
    print("Got connection")
    try:
        for _ in range(5):
            event = json.dumps({
                "time": shared.get_time(),
            })
            await sse.send(event)  # unnamed event
            await asyncio.sleep(5)
    except Exception as e:
        print(f"Error in SSE loop: {e}")
    print("SSE closed")


@app.route('/dose-sse')
@with_sse
async def dose_sse(request, sse):
    print("Got connection")
    old_settings = None
    old_schedule = None
    _old_limits_settings = None
    _old_storage = None
    try:
        for _ in range(30):
            if old_settings != shared.analog_settings or old_schedule != shared.schedule \
                    or _old_limits_settings != shared.limits_settings or _old_storage != shared.storage:
                old_settings = shared.analog_settings.copy()
                old_schedule = shared.schedule.copy()
                _old_limits_settings = shared.limits_settings.copy()
                _old_storage = shared.storage.copy()
                event = json.dumps({
                    "AnalogChartPoints": shared.analog_chart_points,
                    "Settings": shared.analog_settings,
                    "Schedule": shared.schedule,
                    "Limits": shared.limits_settings,
                    "Storage": shared.storage
                })

                print("send Analog Control settigs")
                await sse.send(event)  # unnamed event
            await asyncio.sleep(1)
    except Exception as e:
        print(f"Error in SSE loop: {e}")
    print("SSE closed")


@app.route('/ota-sse')
@with_sse
async def ota_events(request, sse):
    print("Got connection")
    print("file size", firmware_size)
    if firmware_size:
        # Calculate the number of chunks assuming a 4096-byte chunk size
        chunk_size = 4096
        num_chunks = (firmware_size + chunk_size - 1) // chunk_size - 2  # Round up to ensure all data is covered
        print(f"The file will be downloaded in {num_chunks} chunks.")

    while shared.ota_lock:
        print(f"Downloaded:{ota_progress}/{num_chunks}")
        progress = round(ota_progress / num_chunks * 100, 1)
        print(f"progress {progress}%")
        event = {"progress": progress, "size": ota_progress * 4, "status": shared.ota_lock}
        await sse.send(event)  # unnamed event
        await asyncio.sleep(0.5)


@app.route('/ota-upgrade', methods=['GET', 'POST'])
async def ota_upgrade(request):
    if request.method == 'GET':
        if "ota-upgrade.html" in html_files:
            print("Send ota-upgrade.html from RAM")
            response = send_file("ota-upgrade.html", compressed=shared.web_compress,
                                 file_extension=shared.web_file_extension, stream=html_files["ota-upgrade.html"])
        else:
            response = send_file('./static/ota-upgrade.html', compressed=shared.web_compress,
                                 file_extension=shared.web_file_extension)
        response.set_cookie("firmwareLink", firmware_link)
        # Define a regular expression pattern to find "ota_" followed by digits
        pattern = r"ota_(\d+)"

        status = str(ota.status.current_ota)
        print(status)
        # Search for the pattern in the status string
        match = re.search(pattern, status)

        # Extract the ota_ number from the search result
        boot_partition = match.group(1) if match else None

        print(f"boot_partition= <{boot_partition}>")
        print("theme:", shared.settings["theme"])
        response.set_cookie(f'otaPartition', boot_partition)
        response.set_cookie(f'OtaStarted', shared.ota_lock)
        response.set_cookie(f'firmware', RELEASE_TAG)
        response.set_cookie("color", shared.settings["color"])
        response.set_cookie("theme", shared.settings["theme"])

        if addon and hasattr(extension, 'extension_navbar'):
            response.set_cookie("Extension", json.dumps(extension.extension_navbar))

    if request.method == 'POST':
        print("process post request")
        link = request.args.get('link', default=None, type=str)
        new_ota_partition = request.args.get('ota_partition', default=None, type=int)
        cancel_rollback = request.args.get('cancel_rollback', default=False, type=bool)
        print("Download firmware: ", link)
        print("New ota partition:", new_ota_partition)
        print("Cancel rollback:", cancel_rollback)

        global ota_progress
        if link and not shared.ota_lock:
            try:
                print("Start upgrading from link")
                shared.ota_lock = True
                shared.mqtt_worker.service = False  # Stop MQTT worker during OTA
                mcron.remove_all()

                filename = link.split('/')[-1]
                firmware_info = link.replace(".bin", '.json')
                print(f"Download firmware info  {firmware_info}")
                await download_file_async(firmware_info, "micropython.json")
                with open("micropython.json", "r") as read_file:
                    firmware_info = json.load(read_file)
                global firmware_size
                firmware_size = firmware_info["length"]

                await download_file_async(link, filename, progress=True)
                print("Download complete")

                with open('config/storage.json', 'w') as _write_file:
                    # Print the new remaining values
                    print("Store new remaining values: ", shared.storage)
                    json.dump(shared.storage, _write_file)

                ota.update.from_file(filename, reboot=True)
                shared.ota_lock = False

            except Exception as e:
                print("Error: ", e)
                shared.ota_lock = False

        if cancel_rollback:
            print("Cancel firmware rollback")
            ota.rollback.cancel()

        response = {}

    return response


@app.route('/schedule', methods=['GET', 'POST'])
async def schedule_web(request):
    if request.method == 'GET':
        return shared.schedule
    else:
        data = request.json
        print("Got new schedule")
        print(data)

        update_schedule(data)


@app.route('/calibration', methods=['GET', 'POST'])
async def calibration(request):
    if request.method == 'GET':

        if "calibration.html" in html_files:
            print("Send calibration.html from RAM")
            response = send_file("calibration.html", compressed=shared.web_compress,
                                 file_extension=shared.web_file_extension, stream=html_files["calibration.html"])
        else:
            response = send_file('./static/calibration.html', compressed=shared.web_compress,
                                 file_extension=shared.web_file_extension)

        for pump in range(1, shared.PUMP_NUM + 1):
            response.set_cookie(f'calibrationDataPump{pump}',
                                json.dumps(shared.calibration_points[f"calibrationDataPump{pump}"]))
            response.set_cookie(f'PumpNumber', json.dumps({"pump_num": shared.PUMP_NUM}))

        if addon and hasattr(extension, 'extension_navbar'):
            response.set_cookie("Extension", json.dumps(extension.extension_navbar))

        response.set_cookie("pumpNames", json.dumps({"pumpNames": shared.settings["names"]}))
        response.set_cookie("color", shared.settings["color"])
        response.set_cookie("theme", shared.settings["theme"])

    else:
        response = redirect('/')
        response.set_cookie("color", shared.settings["color"])
        response.set_cookie("theme", shared.settings["theme"])
        data = request.json
        for _ in range(1, shared.PUMP_NUM + 1):
            if f"pump{_}" in data:
                new_cal_points = shared.get_points(data[f"pump{_}"])
                if len(new_cal_points) >= 2:
                    print(new_cal_points)
                    print(f"Extrapolate pump{_} flow rate for new calibration points")
                    new_rpm_values, new_flow_rate_values = extrapolate_flow_rate(new_cal_points,
                                                                                 degree=shared.EXTRAPOLATE_ANGLE)
                    print(f"New RPM values:\n{new_rpm_values}")
                    print(f"New Flow values:\n{new_flow_rate_values}")
                    print("1: ", np.interp(1, new_flow_rate_values, new_rpm_values))
                    print("500: ", np.interp(500, new_flow_rate_values, new_rpm_values))
                    print("1000: ", np.interp(1000, new_flow_rate_values, new_rpm_values))
                    shared.chart_points[f"pump{_}"] = (new_rpm_values, new_flow_rate_values)

                    response.set_cookie(f'calibrationDataPump{_}', json.dumps(data[f"pump{_}"]))
                    shared.calibration_points[f'calibrationDataPump{_}'] = data[f"pump{_}"]
                else:
                    print("Not enough cal points")
                    response.set_cookie(f'calibrationDataPump{_}',
                                        json.dumps(shared.calibration_points[f"calibrationDataPump{_}"]))
        with open("config/calibration_points.json", 'w') as write_file:
            write_file.write(json.dumps(shared.calibration_points))
        update_schedule(shared.schedule)
    return response


def setting_responce(request):
    if not shared.ssid:
        src = "settings-captive.html"
    else:
        src = "settings.html"

    if src in html_files:
        print(f"Send {src} from RAM")
        response = send_file(src, compressed=shared.web_compress,
                             file_extension=shared.web_file_extension, stream=html_files[src])
    else:
        print(f"Send {src} from DISK")
        print(html_files)
        response = send_file(f'static/{src}', compressed=shared.web_compress,
                             file_extension=shared.web_file_extension)
    response.set_cookie('hostname', shared.settings["hostname"])
    response.set_cookie('Mac', mac_address)
    response.set_cookie('timezone', shared.settings["timezone"])
    response.set_cookie('timeformat', shared.settings["timeformat"])
    response.set_cookie("mqttTopic", f"/ReefRhythm/{unique_id}/")
    response.set_cookie("mqttBroker", shared.mqtt_settings["broker"])
    response.set_cookie("mqttLogin", shared.mqtt_settings["login"])
    response.set_cookie("analogPeriod", shared.settings["analog_period"])
    response.set_cookie("pumpsCurrent", json.dumps({"current": shared.settings["pumps_current"]}))
    response.set_cookie("pumpInversion", json.dumps({"inversion": shared.settings["inversion"]}))
    response.set_cookie("pumpNames", json.dumps({"pumpNames": shared.settings["names"]}))
    response.set_cookie("color", shared.settings["color"])
    response.set_cookie("theme", shared.settings["theme"])
    response.set_cookie("telegram", shared.settings["telegram"])
    response.set_cookie("whatsappNumber", shared.settings["whatsapp_number"])
    response.set_cookie("whatsappApikey", shared.settings["whatsapp_apikey"])

    response.set_cookie("whatsappEmptyContainerMsg", shared.settings["whatsapp_empty_container_msg"])
    response.set_cookie("telegramEmptyContainerMsg", shared.settings["telegram_empty_container_msg"])

    response.set_cookie("whatsappDoseMsg", shared.settings["whatsapp_dose_msg"])
    response.set_cookie("telegramDoseMsg", shared.settings["telegram_dose_msg"])

    response.set_cookie("emptyContainerLvl", shared.settings["empty_container_lvl"])

    if shared.ssid:
        response.set_cookie('current_ssid', shared.ssid)
        if addon and hasattr(extension, 'extension_navbar'):
            response.set_cookie("Extension", json.dumps(extension.extension_navbar))
    else:
        response.set_cookie('current_ssid', "")
    response.set_cookie(f'PumpNumber', json.dumps({"pump_num": shared.PUMP_NUM}))

    return response


def setting_process_post(request):
    new_ssid = request.json["ssid"]
    new_psw = request.json["psw"]
    new_hostname = request.json["hostname"]
    new_timezone = float(request.json[f"timezone"])
    new_timeformat = int(request.json[f"timeformat"])

    new_mqtt_broker = request.json["mqttBroker"]
    new_mqtt_login = request.json["mqttLogin"]
    new_mqtt_password = request.json["mqttPassword"]
    if not new_mqtt_password and shared.mqtt_settings["password"] and shared.mqtt_settings["broker"]:
        # Save mqtt password if mqtt broker set
        new_mqtt_password = shared.mqtt_settings["password"]

    new_analog_period = request.json["analogPeriod"]

    new_pumps_current = request.json["pumpsCurrent"]

    new_names = json.loads(request.json["pumpNames"])

    new_inversion = request.json["pumpInversion"]

    new_color = request.json["color"]
    new_theme = request.json["theme"]

    new_telegram = request.json["telegram"]
    new_whatsapp_number = request.json["whatsappNumber"]
    new_whatsapp_apikey = request.json["whatsappApikey"]

    new_whatsapp_empty_container_msg = int(request.json["whatsappEmptyContainerMsg"])
    new_telegram_empty_container_msg = int(request.json["telegramEmptyContainerMsg"])
    new_whatapp_dose_msg = int(request.json["whatsappDoseMsg"])
    new_telegram_dose_msg = int(request.json["telegramDoseMsg"])
    new_empty_container_lvl = int(request.json["emptyContainerLvl"])

    if new_ssid and new_psw:
        with open("./config/wifi.json", "w") as f:
            f.write(json.dumps({"ssid": new_ssid, "password": new_psw}))

    with open("./config/mqtt.json", "w") as f:
        f.write(json.dumps({"broker": new_mqtt_broker, "login": new_mqtt_login, "password": new_mqtt_password}))

    new_pump_num = request.json[f"pumpNum"]
    with open("./config/settings.json", "w") as f:
        f.write(json.dumps({"pump_number": new_pump_num,
                            "hostname": new_hostname,
                            "timezone": new_timezone,
                            "timeformat": new_timeformat,
                            "pumps_current": new_pumps_current,
                            "analog_period": new_analog_period,
                            "names": new_names,
                            "inversion": new_inversion,
                            "color": new_color,
                            "theme": new_theme,
                            "telegram": new_telegram,
                            "whatsapp_number": new_whatsapp_number,
                            "whatsapp_apikey": new_whatsapp_apikey,
                            "whatsapp_empty_container_msg": new_whatsapp_empty_container_msg,
                            "telegram_empty_container_msg": new_telegram_empty_container_msg,
                            "whatsapp_dose_msg": new_whatapp_dose_msg,
                            "telegram_dose_msg": new_telegram_dose_msg,
                            "empty_container_lvl": new_empty_container_lvl}))

    with open("./config/analog_settings.json", "w") as f:
        json.dump(shared.analog_settings, f)

    with open('config/storage.json', 'w') as _write_file:
        # Print the new remaining values
        print("Store new remaining values: ", shared.storage)
        json.dump(shared.storage, _write_file)
    print(f"Setting up new wifi {new_ssid}, Reboot...")
    machine.reset()
    return redirect("/settings")


@app.route('/settings', methods=['GET', 'POST'])
async def settings(request):
    if request.method == 'GET':
        response = setting_responce(request)
    else:
        response = setting_process_post(request)
    return response


@app.route('/exec', methods=['POST'])
async def exec(request):
    code = request.json["code"]
    pump = request.json["pump"]
    print(f"[pump{pump}] Testing code: \n", code)
    result, logs = evaluate_expression(code, globals())
    result = True if result is True else False
    print("Result", result)
    return {"result": result, "logs": logs}


@app.route('/exec_save', methods=['POST'])
async def exec_save(request):
    code = request.json["code"]
    pump = request.json["pump"]

    shared.limits_settings[str(pump)] = code
    print("Save new limits config, ", shared.limits_settings)
    with open("./config/limits.json", 'w') as _limits_config:
        json.dump(shared.limits_settings, _limits_config)
    update_schedule(shared.schedule)
    return {'logs': 'Success'}


def update_schedule(data):
    if mcron_keys:
        mcron.remove_all()

    def create_task_with_args(id, rpm, duration, direction, amount, weekdays):
        def task(callback_id, current_time, callback_memory):
            print(f"[{shared.get_time()}] Callback id:", callback_id)
            asyncio.run(
                shared.command_buffer.add_command(stepper_run, None, shared.mks_dict[f"mks" + id], rpm, duration,
                                                  direction,
                                                  shared.rpm_table, shared.limits_settings[str(id)], pump_dose=amount,
                                                  pump_id=int(id),
                                                  weekdays=weekdays))

        return task

    mcron_job_number = 0
    for pump in data:
        id = pump[-1]
        print(f"Add job for {pump}")
        print(data[pump])
        for job in data[pump]:
            amount = job['amount']
            duration = job['duration']
            start_time = job['start_time']
            end_time = job['end_time']
            frequency = job['frequency']
            direction = job['dir']
            if "weekdays" not in job:
                weekdays = [0, 1, 2, 3, 4, 5, 6]
            else:
                weekdays = job["weekdays"]

            desired_flow = amount * (60 / duration)
            desired_rpm_rate = np.interp(desired_flow, shared.chart_points[f"pump{id}"][1],
                                         shared.chart_points[f"pump{id}"][0])

            dir_string = "Clockwise" if direction else "Counterclockwise"

            print(f"[pump{id}] {amount}ml/{duration}sec {start_time}-{end_time} for {frequency} times {dir_string}")
            print(f"Desired flow: {round(desired_flow, 2)}")

            start_time = int(start_time.split(":")[0]) * 60 * 60 + int(start_time.split(":")[1]) * 60

            if end_time:
                end_time = int(end_time.split(":")[0]) * 60 * 60 + int(end_time.split(":")[1]) * 60
                step = (end_time - start_time) // frequency
            else:
                end_time = mcron.PERIOD_DAY
                step = end_time // frequency

            new_job = create_task_with_args(id, desired_rpm_rate, duration, direction, amount, weekdays)
            mcron.insert(mcron.PERIOD_DAY, range(start_time, end_time, step),
                         f'mcron_{mcron_job_number}', new_job)
            mcron_keys.append(f'mcron_{mcron_job_number}')
            mcron_job_number += 1

    if addon:
        mcron_job_number = 0
        print(extension.addon_schedule)
        for job in extension.addon_schedule:

            print("Add job from addon:", job)

            start_time = int(job["start_time"].split(":")[0]) * 60 * 60 + int(job["start_time"].split(":")[1]) * 60
            frequency = job["frequency"]
            if job["end_time"]:
                end_time = int(job["end_time"].split(":")[0]) * 60 * 60 + int(job["end_time"].split(":")[1]) * 60
                step = (end_time - start_time) // frequency
            else:
                end_time = mcron.PERIOD_DAY
                step = end_time // frequency

            mcron.insert(mcron.PERIOD_DAY, range(start_time, end_time, step),
                         f'mcron_ext_{mcron_job_number}', job["job"])
            mcron_keys.append(f'mcron_ext_{mcron_job_number}')
            mcron_job_number += 1

    with open("config/schedule.json", 'w') as write_file:
        write_file.write(json.dumps(data))
    shared.schedule = data.copy()


async def update_sched_onstart():
    while not shared.time_synced:
        await asyncio.sleep(1)
    if addon:
        while not extension.loaded:
            await asyncio.sleep(1)
    update_schedule(shared.schedule)


@restart_on_failure
async def maintain_memory():
    while True:
        gc.collect()
        print(f"free memory {gc.mem_free() // 1024}KB")
        await asyncio.sleep(120)


@restart_on_failure
async def storage_tracker():
    _old_storage = shared.storage.copy()
    while True:
        if _old_storage != shared.storage:
            shared.mqtt_worker.publish_stats(
                mqtt_stats(version=RELEASE_TAG, hostname=shared.settings["hostname"],
                           names=shared.settings["names"],
                           number=shared.PUMP_NUM,
                           current=shared.settings["current"],
                           inversion=shared.settings["inversion"],
                           storage=shared.storage, max_pumps=shared.MAX_PUMPS))
            with open('config/storage.json', 'w') as _write_file:
                # Print the new remaining values
                print("Store new remaining values: ", shared.storage)
                json.dump(shared.storage, _write_file)
                # Update the old remaining values
                _old_storage = _old_storage.copy()
        await asyncio.sleep(3600)


async def main():
    print("Start Web server")
    from connect_wifi import maintain_wifi

    tasks = [
        asyncio.create_task(adc_sampling()),
        asyncio.create_task(analog_control_worker()),
        asyncio.create_task(start_web_server()),
        asyncio.create_task(sync_time()),
        asyncio.create_task(update_sched_onstart()),
        asyncio.create_task(maintain_wifi(shared.wifi_settings["ssid"], shared.wifi_settings["password"],
                                          shared.settings["hostname"])),
        asyncio.create_task(maintain_memory()),
        asyncio.create_task(storage_tracker()),
        asyncio.create_task(shared.telegram_worker.process_messages()),
        asyncio.create_task(shared.whatsapp_worker.process_messages()),
        asyncio.create_task(shared.mqtt_worker.worker())

    ]

    # load async tasks from extension
    if addon:
        print("Extend tasks")
        for _ in extension.extension_tasks:
            task = asyncio.create_task(_())
            tasks.append(task)

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            print(f"Task error: {result}")


async def start_web_server():
    await app.start_server(port=80)


if __name__ == "__main__":
    print("Debugging web.py")
    asyncio.run(main())
