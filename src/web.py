import sys
import time
from machine import Timer

from lib.microdot.microdot import Microdot, redirect, send_file
from lib.microdot.sse import with_sse
import re
import lib.mcron as mcron
from load_configs import *
from lib.exec_code import evaluate_expression
from lib.callmebot import *

try:
    # Import 3-part Add-ons
    import extension

    addon = True
except ImportError as extension_error:
    print("Failed to import extension, ", extension_error)
    addon = False

import binascii

try:
    import uasyncio as asyncio
    # Micropython
    import gc
    import ota.status
    import ota.update
    import ota.rollback

    from release_tag import *
    from lib.umqtt.robust2 import MQTTClient

    mqtt_client = MQTTClient(f"ReefRhythm-{unique_id}", mqtt_broker, keepalive=60, socket_timeout=5)

    USE_RAM = False

except ImportError:
    import asyncio

    print("Mocking on PC")
    from unittest.mock import Mock
    import os

    mcron.remove_all = Mock()
    mcron.insert = Mock()
    mqtt_client = Mock()
    RELEASE_TAG = "local_debug"
    os.system("python ../scripts/compress_web.py --path ./")
    USE_RAM = False


    # Dummy decorator to simulate @micropython.native
    # Creating a more structured mock for micropython module
    class Micropython:
        @staticmethod
        def native(func):
            # Decorator that simply returns the function unchanged
            return func


    # Assign the mock class to a variable with the module's name
    micropython = Micropython()

if USE_RAM:
    print("\nload html to memory")
    # Usage example
    filenames = ['calibration.html', 'doser.html', 'ota-upgrade.html', 'settings.html',
                 'settings-captive.html']  # List your .html.gz files here
    html_files = load_files_to_ram('static/', filenames, f'{web_file_extension}')
    for file in html_files:
        print(file)
else:
    html_files = []

if USE_RAM:
    print("\nload javascripts to memory")
    filenames = ['bootstrap.bundle.min.js', 'chart.min.js']
    js_files = load_files_to_ram('static/javascript/', filenames, f'{web_file_extension}')
else:
    js_files = []

for file in js_files:
    print(file)

if USE_RAM:
    print("\nload css to memory")
    filenames = ['bootstrap.min.css']
    css_files = load_files_to_ram('static/styles/', filenames, f'{web_file_extension}')
else:
    css_files = []

for file in css_files:
    print(file)

app = Microdot()
doser_topic = f"/ReefRhythm/{unique_id}"
gc.collect()
ota_lock = False
ota_progress = 0
firmware_size = None
firmware_link = "http://github.com/telenkov88/reefrhythm-smartdoser/releases/download/latest/micropython.bin"

should_continue = True  # Flag for shutdown
c = 0
mcron.init_timer()
mcron_keys = []
time_synced = False

byte_string = wifi.config('mac')
print(byte_string)
hex_string = binascii.hexlify(byte_string).decode('utf-8')
mac_address = ':'.join(hex_string[i:i + 2] for i in range(0, len(hex_string), 2)).upper()

adc_dict = {}
for _ in analog_pins:
    adc_dict[_] = 0

adc_sampler_started = False


# Define the maximum value for a 32-bit unsigned integer
UINT32_MAX = 0xFFFFFFFF

# Initialize the uptime counter
uptime_counter = 0


# Function to increment the uptime counter
def increment_uptime_counter(timer):
    global uptime_counter
    uptime_counter = (uptime_counter + 1) & UINT32_MAX


# Set up a timer to call increment_uptime_counter every second
timer = Timer(0)
timer.init(period=1000, mode=Timer.PERIODIC, callback=increment_uptime_counter)


async def stepper_run(mks, desired_rpm_rate, execution_time, direction, rpm_table, expression=False,
                      pump_dose=0, pump_id=None, weekdays=None):
    if weekdays is None:
        weekdays = [0, 1, 2, 3, 4, 5, 6]

    def change_remaining():
        print("id:", pump_id, " dose:", pump_dose)
        if pump_dose and pump_id is not None:
            _remaining = storage[f"remaining{pump_id}"] - pump_dose
            _remaining = 0 if _remaining < 0 else _remaining
            _storage = storage[f"pump{pump_id}"]
            storage[f"remaining{pump_id}"] = _remaining
            print(storage)

            if mqtt_broker:
                print("Publish to mqtt")
                _topic = f"{doser_topic}/pump{pump_id}"
                _data = {"id": pump_id, "name": pump_names[pump_id - 1], "dose": pump_dose,
                         "remain": storage[f"remaining{pump_id}"], "storage": storage[f"pump{pump_id}"]}
                print("data", _data)
                print({"topic": _topic, "data": _data})
                mqtt_publish_buffer.append({"topic": _topic, "data": _data})

            _localtime = time.localtime()

            # Extract hours, minutes, and seconds
            hours = _localtime[3]
            minutes = _localtime[4]
            seconds = _localtime[5]

            # Format the time with leading zeros
            formatted_time = f"{hours:02}:{minutes:02}:{seconds:02}"

            msg = ""

            if empty_container_msg and storage[f"pump{pump_id}"]:
                filling_persentage = round(_remaining/storage[f"pump{pump_id}"]*100, 1)
                if 0 < filling_persentage < empty_container_lvl:
                    msg += f"{formatted_time} Pump{pump_id} {pump_names[pump_id - 1]}: Container {filling_persentage}% full%0A"
                elif filling_persentage == 0:
                    msg += f"{formatted_time} Pump{pump_id} {pump_names[pump_id - 1]}: Container empty%0A"

            if dose_msg:
                msg += f"{formatted_time} Pump{pump_id} {pump_names[pump_id - 1]}: "
                msg += f"Dose {pump_dose}mL/{execution_time}sec, {_remaining}/{_storage}mL%0A"
            if telegram and (empty_container_msg or dose_msg):
                telegram_buffer.append(msg)
            if whatsapp_apikey and whatsapp_number and (empty_container_msg or dose_msg):
                whatsapp_buffer.append(msg)


    wday = time.localtime()[6]
    print(f"Check weekdays: {wday} in {weekdays}")
    if wday not in weekdays:
        print("Skip dosing job")
        return

    print(f"Desired {to_float(desired_rpm_rate)}rpm, mstep")
    if inversion[pump_id - 1]:
        direction = 0 if direction == 1 else 1

    if expression:
        print("Check expression: ", expression)
        result, logs = evaluate_expression(expression, globals())
        if result:
            print(f"Limits check pass")
            calc_time = move_with_rpm(mks, desired_rpm_rate, execution_time, rpm_table, direction)
            change_remaining()
            return [calc_time]
    else:
        calc_time = move_with_rpm(mks, desired_rpm_rate, execution_time, rpm_table, direction)
        change_remaining()
        return [calc_time]
    print(f"Limits check not pass, skip dosing")
    return False


async def stepper_stop(mks):
    print(f"Stop {id} stepper")
    return mks.stop()


@micropython.native
async def adc_sampling():
    global adc_dict
    sampling_size = 5
    sampling_delay = 1 / sampling_size
    global adc_sampler_started
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
            adc_dict[pin] = sum(adc_buffer[pin]) // sampling_size
        adc_sampler_started = True
        # print(f"Pin{pin} buffer {[int(x) for x in adc_buffer[pin]]}")
        # print(adc_dict)


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


def to_float(arr):
    if isinstance(arr, np.ndarray):
        # If it's a single-item NumPy array, extract the item and return
        return arr[0]
    else:
        return arr


async def analog_control_worker():
    while not adc_sampler_started:
        print("Wait for adc sampler finish firts cycle")
        await asyncio.sleep(0.1)
    print("Init adc worker")
    print("adc_dict:", adc_dict)
    # Init Pumps
    adc_buffer_values = {}
    for i, en in enumerate(analog_en):
        if en and len(analog_settings[f"pump{i + 1}"]["points"]) >= 2:
            if analog_settings[f"pump{i + 1}"]["pin"] != 99:
                print("adc_buffer_values append ", adc_dict[analog_settings[f"pump{i + 1}"]["pin"]])
                adc_buffer_values[i] = [adc_dict[analog_settings[f"pump{i + 1}"]["pin"]]]
            else:
                adc_buffer_values[i] = [4095]
        else:
            adc_buffer_values[i] = [0]
    print("ota_lock:", ota_lock)
    print(adc_buffer_values)
    while True:
        print("Analog worker cycle")
        while ota_lock:
            await asyncio.sleep(200)

        for i, en in enumerate(analog_en):
            if en and len(analog_settings[f"pump{i + 1}"]["points"]) >= 2:
                print(f"\r\n================\r\nRun pump{i + 1}, PIN", analog_settings[f"pump{i + 1}"]["pin"])
                print(adc_buffer_values[i])
                adc_average = sum(adc_buffer_values[i]) // len(adc_buffer_values[i])
                print("ADC value: ", adc_average)
                adc_signal = adc_average / 40.95
                print(f"Signal: {adc_signal}")
                signals, flow_rates = zip(*analog_chart_points[f"pump{i + 1}"])
                desired_flow = to_float(np.interp(adc_signal, signals, flow_rates))
                amount = desired_flow * analog_period / 60
                print("Desired flow", desired_flow)
                print("Amount:", amount)
                if desired_flow >= 0.01:
                    desired_rpm_rate = to_float(
                        np.interp(desired_flow, chart_points[f"pump{i + 1}"][1], chart_points[f"pump{i + 1}"][0]))

                    await command_buffer.add_command(stepper_run, None, mks_dict[f"mks{i + 1}"], desired_rpm_rate,
                                                     analog_period + 5,
                                                     analog_settings[f"pump{i + 1}"]["dir"], rpm_table,
                                                     limits_dict[i + 1], pump_dose=amount, pump_id=(i + 1))
        for _ in range(len(analog_en)):
            adc_buffer_values[_] = []
        for x in range(0, analog_period):
            for i, en in enumerate(analog_en):
                if en and analog_settings[f"pump{i + 1}"]["pin"] != 99:
                    adc_buffer_values[i].append(adc_dict[analog_settings[f"pump{i + 1}"]["pin"]])
                else:
                    adc_buffer_values[i] = [4095]

            await asyncio.sleep(1)


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
    points = chart_points[f"pump{pump_number}"][0].tolist()
    return json.dumps(points)


@app.route('/get_flow_points')
async def get_flow_points(request):
    pump_number = request.args.get('pump', default=1, type=int)
    print(f"return flow points for pump{pump_number}")
    points = chart_points[f"pump{pump_number}"][1].tolist()
    print(points)
    return json.dumps(points)


@app.route('/get_analog_chart_points')
async def get_analog_chart_points(request):
    pump_number = request.args.get('pump', default=1, type=int)
    print(f"return analog input points for pump{pump_number}")
    points = analog_chart_points[f"pump{pump_number}"]
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
        return send_file(path, compressed=web_compress,
                         file_extension=web_file_extension, stream=css_files[path])
    return send_file('static/styles/' + path, compressed=web_compress,
                     file_extension=web_file_extension)


@app.route('/javascript/<path:path>')
async def javascript(request, path):
    if '..' in path:
        # directory traversal is not allowed
        return 'Not found', 404
    print(f"Send file static/javascript/{path}")
    if path in js_files:
        print(f"send js {path} from RAM")
        return send_file(path, compressed=web_compress,
                         file_extension=web_file_extension, stream=js_files[path])
    else:
        print(f"send js {path} from DISK")
        return send_file('static/javascript/' + path, compressed=web_compress,
                         file_extension=web_file_extension)


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


@app.route('/stop')
async def stop(request):
    _id = request.args.get('id', default=1, type=int)

    print(f"[ID {_id}] Stop")
    callback_result_future = CustomFuture()

    def callback(result):
        print(f"Callback received result: {result}")
        callback_result_future.set_result({"result": result})

    task = asyncio.create_task(
        command_buffer.add_command(stepper_stop, callback, mks_dict[f"mks{_id}"]))
    await task

    await callback_result_future.wait()
    callback_result = await callback_result_future.wait()
    print("Result of callback:", callback_result)

    return callback_result


@app.route('/run')
async def run_with_rpm(request):
    id = request.args.get('id', default=1, type=int)
    rpm = request.args.get('rpm', default=1, type=float)
    direction = request.args.get('direction', default=1, type=int)
    execution_time = request.args.get('duration', default=1, type=float)

    print(f"[ID {id}] Run {rpm}RPM for {execution_time}sec Dir={direction}")

    callback_result_future = CustomFuture()

    def callback(result):
        print(f"Callback received result: {result}")
        callback_result_future.set_result({"time": result[0]})

    task = asyncio.create_task(
        command_buffer.add_command(stepper_run, callback, mks_dict[f"mks{id}"], rpm, execution_time, direction,
                                   rpm_table, False, pump_dose=0, pump_id=id))
    await task

    await callback_result_future.wait()
    callback_result = await callback_result_future.wait()
    print("Result of callback:", callback_result)

    return callback_result


@app.route('/dose')
async def dose(request):
    id = request.args.get('id', default=1, type=int)
    amount = request.args.get('amount', default=0, type=float)
    execution_time = request.args.get('duration', default=0, type=float)
    direction = request.args.get('direction', default=1, type=int)
    print(f"[Pump{id}]")
    print(f"Dose {amount}ml in {execution_time}s ")

    # Calculate RPM for Flow Rate
    desired_flow = amount * (60 / execution_time)
    print(f"Desired flow: {round(desired_flow, 2)}")
    print(f"Direction: {direction}")
    desired_rpm_rate = np.interp(desired_flow, chart_points[f"pump{id}"][1], chart_points[f"pump{id}"][0])
    desired_rpm_rate = to_float(desired_rpm_rate)

    callback_result_future = CustomFuture()

    def callback(result):
        print(f"Callback received result: {result}")
        callback_result_future.set_result({"flow": desired_flow, "rpm": desired_rpm_rate, "time": result[0]})

    task = asyncio.create_task(
        command_buffer.add_command(stepper_run, callback, mks_dict[f"mks{id}"], desired_rpm_rate, execution_time,
                                   direction, rpm_table, pump_dose=amount, pump_id=id))
    # await uart_buffer.process_commands()
    await task

    await callback_result_future.wait()
    callback_result = await callback_result_future.wait()
    print("Result of callback:", callback_result)

    return callback_result


@app.route('/', methods=['GET', 'POST'])
async def index(request):
    if request.method == 'GET':
        # Captive portal
        if not ssid:
            return setting_responce(request)

        if "doser.html" in html_files:
            print("Send doser.html.gz from RAM")
            response = send_file("doser.html", compressed=web_compress,
                                 file_extension=web_file_extension, stream=html_files["doser.html"])
        else:
            response = send_file('./static/doser.html', compressed=web_compress,
                                 file_extension=web_file_extension)

        response.set_cookie(f'AnalogPins', json.dumps(analog_pins))
        response.set_cookie(f'PumpNumber', json.dumps({"pump_num": PUMP_NUM}))
        response.set_cookie(f'timeformat', timeformat)
        response.set_cookie("pumpNames", json.dumps({"pumpNames": pump_names}))
        response.set_cookie("color", color)
        response.set_cookie("theme", theme)
        print("color ", color)
        print("theme ", theme)

        if addon and hasattr(extension, 'extension_navbar'):
            response.set_cookie("Extension", json.dumps(extension.extension_navbar))

        return response
    else:
        # Captive portal
        if not ssid:
            return setting_process_post(request)

        response = redirect('/')
        data = request.json
        print(data)
        for _ in range(1, PUMP_NUM + 1):
            if f"pump{_}" in data:
                if len(data[f"pump{_}"]["points"]) >= 2:
                    # response.set_cookie(f'AnalogInputDataPump{_}', json.dumps(data[f"pump{_}"]))

                    points = [(d['analogInput'], d['flowRate']) for d in data[f"pump{_}"]["points"]]
                    analog_chart_points[f"pump{_}"] = linear_interpolation(points)
                    print(analog_chart_points[f"pump{_}"])
                    # Save new settings
                    analog_settings[f"pump{_}"] = data[f"pump{_}"]
                    analog_en[_ - 1] = analog_settings[f"pump{_}"]["enable"]

                else:
                    print(f"Pump{_} Not enough Analog Input points")
        with open("config/analog_settings.json", 'w') as write_file:
            write_file.write(json.dumps(analog_settings))
        return response


@app.route('/time')
@with_sse
async def dose_ssetime(request, sse):
    print("Got connection")
    try:
        for _ in range(5):
            event = json.dumps({
                "time": get_time(),
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
            if old_settings != analog_settings or old_schedule != schedule or _old_limits_settings != limits_dict or _old_storage != storage:
                old_settings = analog_settings.copy()
                old_schedule = schedule.copy()
                _old_limits_settings = limits_dict.copy()
                _old_storage = storage.copy()
                event = json.dumps({
                    "AnalogChartPoints": analog_chart_points,
                    "Settings": analog_settings,
                    "Schedule": schedule,
                    "Limits": limits_dict,
                    "Storage": storage
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

    while ota_lock:
        print(f"Downloaded:{ota_progress}/{num_chunks}")
        progress = round(ota_progress / num_chunks * 100, 1)
        print(f"progress {progress}%")
        event = {"progress": progress, "size": ota_progress * 4, "status": ota_lock}
        await sse.send(event)  # unnamed event
        await asyncio.sleep(0.5)


@app.route('/ota-upgrade', methods=['GET', 'POST'])
async def ota_upgrade(request):
    if request.method == 'GET':
        global ota_lock

        if "ota-upgrade.html" in html_files:
            print("Send ota-upgrade.html from RAM")
            response = send_file("ota-upgrade.html", compressed=web_compress,
                                 file_extension=web_file_extension, stream=html_files["ota-upgrade.html"])
        else:
            response = send_file('./static/ota-upgrade.html', compressed=web_compress,
                                 file_extension=web_file_extension)
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
        print("theme:", theme)
        response.set_cookie(f'otaPartition', boot_partition)
        response.set_cookie(f'OtaStarted', ota_lock)
        response.set_cookie(f'firmware', RELEASE_TAG)
        response.set_cookie("color", color)
        response.set_cookie("theme", theme)

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
        if link and not ota_lock:
            try:
                print("Start upgrading from link")
                ota_lock = True
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
                    print("Store new remaining values: ", storage)
                    json.dump(storage, _write_file)

                ota.update.from_file(filename, reboot=True)
                ota_lock = False

            except Exception as e:
                print("Error: ", e)
                ota_lock = False

        if cancel_rollback:
            print("Cancel firmware rollback")
            ota.rollback.cancel()

        response = {}

    return response


@app.route('/schedule', methods=['GET', 'POST'])
async def schedule_web(request):
    if request.method == 'GET':
        return schedule
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
            response = send_file("calibration.html", compressed=web_compress,
                                 file_extension=web_file_extension, stream=html_files["calibration.html"])
        else:
            response = send_file('./static/calibration.html', compressed=web_compress,
                                 file_extension=web_file_extension)

        for pump in range(1, PUMP_NUM + 1):
            response.set_cookie(f'calibrationDataPump{pump}',
                                json.dumps(calibration_points[f"calibrationDataPump{pump}"]))
            response.set_cookie(f'PumpNumber', json.dumps({"pump_num": PUMP_NUM}))

        if addon and hasattr(extension, 'extension_navbar'):
            response.set_cookie("Extension", json.dumps(extension.extension_navbar))

        response.set_cookie("pumpNames", json.dumps({"pumpNames": pump_names}))
        response.set_cookie("color", color)
        response.set_cookie("theme", theme)

    else:
        response = redirect('/')
        response.set_cookie("color", color)
        response.set_cookie("theme", theme)
        data = request.json
        for _ in range(1, PUMP_NUM + 1):
            if f"pump{_}" in data:
                new_cal_points = get_points(data[f"pump{_}"])
                if len(new_cal_points) >= 2:
                    print(new_cal_points)
                    print(f"Extrapolate pump{_} flow rate for new calibration points")
                    new_rpm_values, new_flow_rate_values = extrapolate_flow_rate(new_cal_points,
                                                                                 degree=EXTRAPOLATE_ANGLE)
                    print(f"New RPM values:\n{new_rpm_values}")
                    print(f"New Flow values:\n{new_flow_rate_values}")
                    print("1: ", np.interp(1, new_flow_rate_values, new_rpm_values))
                    print("500: ", np.interp(500, new_flow_rate_values, new_rpm_values))
                    print("1000: ", np.interp(1000, new_flow_rate_values, new_rpm_values))
                    chart_points[f"pump{_}"] = (new_rpm_values, new_flow_rate_values)

                    response.set_cookie(f'calibrationDataPump{_}', json.dumps(data[f"pump{_}"]))
                    calibration_points[f'calibrationDataPump{_}'] = data[f"pump{_}"]
                else:
                    print("Not enough cal points")
                    response.set_cookie(f'calibrationDataPump{_}',
                                        json.dumps(calibration_points[f"calibrationDataPump{_}"]))
        with open("config/calibration_points.json", 'w') as write_file:
            write_file.write(json.dumps(calibration_points))
        update_schedule(schedule)
    return response


def setting_responce(request):
    if not 'ssid' in globals():
        src = "settings-captive.html"
    else:
        src = "settings.html"

    if src in html_files:
        print(f"Send {src} from RAM")
        response = send_file(src, compressed=web_compress,
                             file_extension=web_file_extension, stream=html_files[src])
    else:
        print(f"Send {src} from DISK")
        print(html_files)
        response = send_file(f'static/{src}', compressed=web_compress,
                             file_extension=web_file_extension)
    response.set_cookie('hostname', hostname)
    response.set_cookie('Mac', mac_address)
    response.set_cookie('timezone', timezone)
    response.set_cookie('timeformat', timeformat)
    response.set_cookie("mqttTopic", f"/ReefRhythm/{unique_id}/")
    response.set_cookie("mqttBroker", mqtt_broker)
    response.set_cookie("mqttLogin", mqtt_login)
    response.set_cookie("analogPeriod", analog_period)
    response.set_cookie("pumpsCurrent", json.dumps({"current": pumps_current}))
    response.set_cookie("analogPeriod", analog_period)
    response.set_cookie("pumpInversion", json.dumps({"inversion": inversion}))
    response.set_cookie("pumpNames", json.dumps({"pumpNames": pump_names}))
    response.set_cookie("color", color)
    response.set_cookie("theme", theme)
    response.set_cookie("telegram", telegram)
    response.set_cookie("whatsappNumber", whatsapp_number)
    response.set_cookie("whatsappApikey", whatsapp_apikey)
    response.set_cookie("emptyContainerMsg", empty_container_msg)
    response.set_cookie("emptyContainerLvl", empty_container_lvl)
    response.set_cookie("doseMsg", dose_msg)

    if 'ssid' in globals():
        response.set_cookie('current_ssid', ssid)
        if addon and hasattr(extension, 'extension_navbar'):
            response.set_cookie("Extension", json.dumps(extension.extension_navbar))
    else:
        response.set_cookie('current_ssid', "")
    response.set_cookie(f'PumpNumber', json.dumps({"pump_num": PUMP_NUM}))

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

    new_analog_period = request.json["analogPeriod"]

    new_pumps_current = request.json["pumpsCurrent"]

    new_names = json.loads(request.json["pumpNames"])

    new_inversion = request.json["pumpInversion"]

    new_color = request.json["color"]
    new_theme = request.json["theme"]

    new_telegram = request.json["telegram"]
    new_whatsapp_number = request.json["whatsappNumber"]
    new_whatsapp_apikey = request.json["whatsappApikey"]

    new_empty_container_msg = int(request.json["emptyContainerMsg"])
    new_empty_container_lvl = int(request.json["emptyContainerLvl"])
    new_dose_msg = int(request.json["doseMsg"])

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
                            "empty_container_msg": new_empty_container_msg,
                            "empty_container_lvl": new_empty_container_lvl,
                            "dose_msg": new_dose_msg}))

    with open("./config/analog_settings.json", "w") as f:
        json.dump(analog_settings, f)

    with open('config/storage.json', 'w') as _write_file:
        # Print the new remaining values
        print("Store new remaining values: ", storage)
        json.dump(storage, _write_file)
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
async def settings(request):
    code = request.json["code"]
    pump = request.json["pump"]
    print(f"[pump{pump}]Testing code:\n", code)
    result, logs = evaluate_expression(code, globals())
    result = True if result is True else False
    print("Result", result)
    return {"result": result, "logs": logs}


@app.route('/exec_save', methods=['POST'])
async def settings(request):
    code = request.json["code"]
    pump = int(request.json["pump"])

    limits_dict[pump] = code
    print("Save new limits config, ", limits_dict)
    with open("./config/limits.json", 'w') as _limits_config:
        _limits_config.write(json.dumps(limits_dict))
    update_schedule(schedule)
    return {'logs': 'Success'}


@app.route('/refill', methods=['POST'])
async def refill(request):
    global storage
    _storage = request.json
    for _ in range(MAX_PUMPS):
        storage[f"pump{_ + 1}"] = _storage[f"pump{_ + 1}"]
        storage[f"remaining{_ + 1}"] = _storage[f"remaining{_ + 1}"]
    print("New storage data: ", storage)
    with open("config/storage.json", 'w') as write_file:
        json.dump(storage, write_file)
    return {}


def update_schedule(data):
    if mcron_keys:
        mcron.remove_all()

    def create_task_with_args(id, rpm, duration, direction, amount, weekdays):
        def task(callback_id, current_time, callback_memory):
            print(f"[{get_time()}] Callback id:", callback_id)
            asyncio.run(command_buffer.add_command(stepper_run, None, mks_dict[f"mks" + id], rpm, duration, direction,
                                                   rpm_table, limits_dict[int(id)], pump_dose=amount, pump_id=int(id),
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
            desired_rpm_rate = np.interp(desired_flow, chart_points[f"pump{id}"][1], chart_points[f"pump{id}"][0])

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
    global schedule
    schedule = data.copy()


async def sync_time():
    ntptime.host = ntphost
    global time_synced
    while not wifi.isconnected():
        await asyncio.sleep(1)

    # Initial time sync is Mandatory to job scheduler
    while not time_synced:
        i = 0
        try:
            print("Local time before synchronization：%s" % str(time.localtime()))
            ntptime.settime(timezone)
            print("Local time after synchronization：%s" % str(time.localtime()))
            time_synced = True
            break
        except Exception as _e:
            i += 1
            if i == 10:
                wifi.active(False)
            elif i > 40:
                machine.reset()
            print("Failed to sync time on start. ", _e)
        await asyncio.sleep(10)

    while True:
        if wifi.isconnected():
            x = 0
            while True:
                try:
                    print("Local time before synchronization：%s" % str(time.localtime()))
                    ntptime.settime(timezone)
                    print("Local time after synchronization：%s" % str(time.localtime()))
                    time_synced = True
                    break
                except Exception as _e:
                    x += 1
                    print(f'{x} time sync failed, Error: {_e}')
                if x >= 3600:
                    print("Time sync not working, reboot")
                    sys.exit()

                await asyncio.sleep(60)
        else:
            print("wifi disconnected")

        await asyncio.sleep(1800)


async def update_sched_onstart():
    while not time_synced:
        await asyncio.sleep(1)
    if addon:
        while not extension.loaded:
            await asyncio.sleep(1)
    update_schedule(schedule)


async def maintain_memory():
    while True:
        gc.collect()
        print(f"free memory {gc.mem_free() // 1024}KB")
        await asyncio.sleep(120)


async def mqtt_worker():
    if not mqtt_broker:
        return True
    while not time_synced:
        await asyncio.sleep(1)
    print("Start MQTT")

    def sub(topic, msg, retain, dup):
        def decode_body():
            try:
                print(msg.decode('ascii'))
                mqtt_body = json.loads(msg.decode('ascii'))
                print(mqtt_body)
                return mqtt_body
            except Exception as mqtt_decode_e:
                print("Failed to decode mqtt message: {msg}, ", mqtt_decode_e)
            return False

        def check_dose_parameters(cmd):
            if all(key in cmd for key in ["id", "amount", "duration", "direction"]):
                # Check the range and validity of each parameter
                return (1 <= cmd["id"] <= PUMP_NUM and
                        cmd["amount"] > 0 and
                        1 <= cmd["duration"] <= 3600 and
                        cmd["direction"] in [0, 1])
            return False

        def check_run_parameters(cmd):
            if all(key in cmd for key in ["id", "rpm", "duration", "direction"]):
                # Check the range and validity of each parameter
                return (1 <= cmd["id"] <= PUMP_NUM and
                        0.5 <= cmd["rpm"] <= 1000 and
                        1 <= cmd["duration"] <= 3600 and
                        cmd["direction"] in [0, 1])
            return False

        def check_stop_parameters(cmd):
            if "id" in cmd:
                return 1 <= cmd["id"] <= PUMP_NUM
            return False

        print('received message %s on topic %s' % (msg.decode(), topic.decode()))
        if topic.decode() == f"/ReefRhythm/{unique_id}/dose":
            command = decode_body()
            if command and check_dose_parameters(command):
                print("Dose command ", command)
                mqtt_dose_buffer.append(command)
            else:
                print("error in syntax: ", command)

        elif topic.decode() == f"/ReefRhythm/{unique_id}/run":
            command = decode_body()
            if command and check_run_parameters(command):
                print("Run command", command)
                mqtt_run_buffer.append(command)
            else:
                print("error in syntax: ", command)
        elif topic.decode() == f"/ReefRhythm/{unique_id}/stop":
            command = decode_body()
            if command and check_stop_parameters(command):
                print("Stop command", command)
                mqtt_stop_buffer.append(command)
            else:
                print("error in syntax: ", command)
        elif topic.decode() == f"/ReefRhythm/{unique_id}/refill":
            command = decode_body()
            if command and check_stop_parameters(command):
                print("Refilling command", command)
                mqtt_refill_buffer.append(command)
            else:
                print("error in syntax: ", command)

    mqtt_client.pswd = mqtt_password
    mqtt_client.user = mqtt_login

    # Option, limits the possibility of only one unique message being queued.
    mqtt_client.NO_QUEUE_DUPS = True
    # Limit the number of unsent messages in the queue.
    mqtt_client.MSG_QUEUE_MAX = 5

    last_will_topic = f"/ReefRhythm/{unique_id}/status"
    global doser_topic
    global mqtt_publish_buffer
    print("MQTT last will topic: ", last_will_topic)
    mqtt_client.set_last_will(last_will_topic, 'Disconnected', retain=True)

    mqtt_client.set_callback(sub)
    try:
        print(f"connect to {mqtt_broker}")
        mqtt_client.connect()
        print(f"subscribe {doser_topic}/dose")
        mqtt_client.subscribe(f"{doser_topic}/dose")
        print(f"subscribe {doser_topic}/run")
        mqtt_client.subscribe(f"{doser_topic}/run")
        print(f"subscribe {doser_topic}/stop")
        mqtt_client.subscribe(f"{doser_topic}/stop")
        print(f"subscribe {doser_topic}/refill")
        mqtt_client.subscribe(f"{doser_topic}/refill")
        print(f"subscribe $SYS/broker/uptime")
        mqtt_client.subscribe("$SYS/broker/uptime")
        mqtt_client.publish(last_will_topic, 'Connected', retain=True)

        msg = {"free_mem": gc.mem_free() // 1024}
        mqtt_client.publish(f"{doser_topic}/free_mem", json.dumps(msg))
    except Exception as e:
        print("Failed to init MQTT ", e)

    import _thread

    def blocking_reconnect(mqtt, result):
        try:
            print("mqtt reconnect")
            mqtt_client.log()
            mqtt.reconnect()
            result.append(mqtt.is_conn_issue())
        except Exception as _e:
            print("MQTT Error: ", _e)
            result.append(e)


    while 1:
        while ota_lock:
            await asyncio.sleep(200)
        # At this point in the code you must consider how to handle
        # connection errors.  And how often to resume the connection.
        try:
            if mqtt_client.is_conn_issue():
                while mqtt_client.is_conn_issue():
                    # If the connection is successful, the is_conn_issue
                    # method will not return a connection error.
                    result = []
                    _thread.start_new_thread(blocking_reconnect, (mqtt_client, result))
                    while not result:
                        print("Wait MQTT reconnect")
                        await asyncio.sleep(1)
                    #mqtt_client.disconnect()
                    #mqtt_client.reconnect()
                    if not mqtt_client.is_conn_issue():
                        print("mqtt publush status")
                        mqtt_client.publish(last_will_topic, 'Connected', retain=True)
                        print("mqtt resubscribe")
                        mqtt_client.resubscribe()

                        if mqtt_publish_buffer:
                            for msg in mqtt_publish_buffer:
                                mqtt_client.publish(msg["topic"], json.dumps(msg["data"]))
                            mqtt_publish_buffer = []
                        break
                    print("Failed to reconnect MQTT")
                    await asyncio.sleep(60)

            # WARNING!!!
            # The below functions should be run as often as possible.
            # There may be a problem with the connection. (MQTTException(7,), 9)
            # In the following way, we clear the queue.
            if mqtt_publish_buffer:
                print("MQTT publish buffer")
            for _ in range(50):
                # print("mqtt check_msg")
                if mqtt_client.is_conn_issue():
                    mqtt_client.log()
                    break
                    for msg in mqtt_publish_buffer:
                        print("MQTT publish ", msg)
                        mqtt_client.publish(msg["topic"], json.dumps(msg["data"]))
                    mqtt_publish_buffer = []
                if (_ + 1) % 20 == 0:
                    msg = {"free_mem": gc.mem_free() // 1024}
                    mqtt_client.publish(f"{doser_topic}/free_mem", json.dumps(msg))
                    mqtt_client.publish(f"{doser_topic}/uptime", str(uptime_counter))
                mqtt_client.check_msg()  # needed when publish(qos=1), ping(), subscribe()
                mqtt_client.send_queue()  # needed when using the caching capabilities for unsent messages
                #if not mqtt_client.things_to_do():
                #    break
                await asyncio.sleep(1)
            print("MQTT finished cycle")
        except Exception as e:
            print("MQTT Error: ", e)
            await asyncio.sleep(10)
        await asyncio.sleep(0.5)


mqtt_dose_buffer = []
mqtt_run_buffer = []
mqtt_stop_buffer = []
mqtt_refill_buffer = []
mqtt_publish_buffer = []


async def process_mqtt_cmd():
    while True:
        if mqtt_dose_buffer:
            print("Process mqtt Dose command")
            command = mqtt_dose_buffer[0]
            del mqtt_dose_buffer[0]
            desired_flow = command["amount"] * (60 / command["duration"])
            print(f"Desired flow: {round(desired_flow, 2)}")
            print(f"Direction: {command['direction']}")
            desired_rpm_rate = np.interp(desired_flow, chart_points[f"pump{command['id']}"][1],
                                         chart_points[f"pump{command['id']}"][0])
            print("Calculated RPM: ", desired_rpm_rate)
            await command_buffer.add_command(stepper_run, None, mks_dict[f"mks{command['id']}"], desired_rpm_rate,
                                             command['duration'], command['direction'], rpm_table,
                                             limits_dict[int(command['id'])], pump_dose=command["amount"],
                                             pump_id=int(command['id']))

        if mqtt_run_buffer:
            print("Process mqtt Run command")
            command = mqtt_run_buffer[0]
            del mqtt_run_buffer[0]
            print(f"Direction: {command['direction']}")
            desired_rpm_rate = command['rpm']
            print("Desired RPM: ", desired_rpm_rate)
            await command_buffer.add_command(stepper_run, None, mks_dict[f"mks{command['id']}"], desired_rpm_rate,
                                             command['duration'], command['direction'], rpm_table,
                                             limits_dict[int(command['id'])], pump_dose=None,
                                             pump_id=int(command['id']))

        if mqtt_stop_buffer:
            print("Process mqtt Stop command")
            command = mqtt_stop_buffer[0]
            del mqtt_stop_buffer[0]
            print(f"Stop pump{command['id']}")
            await command_buffer.add_command(stepper_stop, None, mks_dict[f"mks{command['id']}"])

        if mqtt_refill_buffer:
            print("Process mqtt refill command")
            command = mqtt_refill_buffer[0]
            del mqtt_refill_buffer[0]
            print(f"Refilling pump{command['id']} storage")
            storage[f"remaining{command['id']}"] = storage[f"pump{command['id']}"]
            print("Publish to mqtt")
            _pump_id = command['id']
            _topic = f"{doser_topic}/pump{_pump_id}"
            _data = {"id": _pump_id, "name": pump_names[_pump_id - 1], "dose": 0,
                     "remain": storage[f"remaining{_pump_id}"], "storage": storage[f"pump{_pump_id}"]}
            print("data", _data)
            print({"topic": _topic, "data": _data})
            mqtt_publish_buffer.append({"topic": _topic, "data": _data})

        await asyncio.sleep(1)


async def storage_tracker():
    global storage
    _old_storage = storage.copy()
    while True:
        if _old_storage != storage:
            with open('config/storage.json', 'w') as _write_file:
                # Print the new remaining values
                print("Store new remaining values: ", storage)
                json.dump(storage, _write_file)
                # Update the old remaining values
                _old_storage = _old_storage.copy()
        await asyncio.sleep(3600)


telegram_buffer = []


async def telegram_worker():
    global telegram_buffer
    global ota_lock
    if telegram:
        telegram_webhook = Telegram(telegram)
    else:
        return
    while not time_synced:
        await asyncio.sleep(1)
    print("Start Telegram CallmeBot")
    while True:
        while ota_lock:
            await asyncio.sleep(5)

        print("Telegram worker cycle")

        if telegram_buffer:
            print("Try to send telegram notification")
            print(telegram_buffer)
            if not wifi.isconnected():
                print("Telegram notification- wait for wifi")
            while not wifi.isconnected():
                await asyncio.sleep(0.5)

            try:
                _msg = ""
                for _ in telegram_buffer:
                    _msg = _msg + _
                print("Send message:\r\n", _msg.replace("%0A", "\r\n"))
                response = telegram_webhook.send_message(_msg)
                if not response:
                    print("Telegram nofirication crash")
                elif response.status_code == 200 and "Telegram Error Code: 400" not in response.text:
                    print("Telegram notification succeed")
                    telegram_buffer = []
                elif response.status_code in [404, 203]:
                    print("Telegram notification rejected")
                    telegram_buffer = []
                else:
                    print("Telegram notification failed")
                if response:
                    print("Status Code: ", response.status_code, "\n", response.text)
            except Exception as e:
                print("Failed to send Telegram message: ", e)
            while len(telegram_buffer) > 600:
                print("telegram_buffer full, clean")
                del telegram_buffer[0]
        print("Telegram worker cycle finished, buffer:", whatsapp_buffer)

        await asyncio.sleep(600)


whatsapp_buffer = []


async def whatsapp_worker():
    global whatsapp_buffer
    global ota_lock
    if whatsapp_number and whatsapp_apikey:
        whatsapp_webhook = Whatsapp(whatsapp_number, whatsapp_apikey)
    else:
        return
    while not time_synced:
        await asyncio.sleep(1)
    print("Start WhatsApp CallmeBot")
    while True:
        while ota_lock:
            await asyncio.sleep(5)
        print("WhatsApp worker cycle")

        if whatsapp_buffer:
            print("Try to send Whatsapp notification")
            print(whatsapp_buffer)
            if not wifi.isconnected():
                print("WhatsApp notification- wait for wifi")
            while not wifi.isconnected():
                await asyncio.sleep(0.5)
            try:
                _msg = ""
                for _ in whatsapp_buffer:
                    _msg = _msg + _
                print("Send message:\r\n", _msg.replace("%0A", "\r\n"))
                response = whatsapp_webhook.send_message(_msg)
                if not response:
                    print("Whatsapp nofirication crash")
                elif response.status_code == 200:
                    print("Whatsapp notification succeed")
                    whatsapp_buffer = []
                elif response.status_code in [404, 203]:
                    print("Whatsapp notification rejected")
                    whatsapp_buffer = []
                else:
                    print("Whatsapp notification failed")
                if response:
                    print("Status Code: ", response.status_code, "\n", response.text)

            except Exception as e:
                print("Failed to send Whatsapp message: ", e)
            while len(whatsapp_buffer) > 600:
                print("whatsapp buffer full, clean")
                del whatsapp_buffer[0]
        print("Whatsapp worker cycle finished, buffer:", whatsapp_buffer)


        await asyncio.sleep(600)


async def main():
    print("Start Web server")
    from connect_wifi import maintain_wifi

    # Importing external @app.route to support add-ons

    tasks = [
        asyncio.create_task(adc_sampling()),
        asyncio.create_task(analog_control_worker()),
        asyncio.create_task(start_web_server()),
        asyncio.create_task(sync_time()),
        asyncio.create_task(update_sched_onstart()),
        asyncio.create_task(maintain_wifi(ssid, password, hostname)),
        asyncio.create_task(maintain_memory()),
        asyncio.create_task(mqtt_worker()),
        asyncio.create_task(process_mqtt_cmd()),
        asyncio.create_task(storage_tracker()),
        asyncio.create_task(telegram_worker()),
        asyncio.create_task(whatsapp_worker())
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
