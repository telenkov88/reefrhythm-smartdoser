from lib.microdot.microdot import Microdot, redirect, send_file
from lib.microdot.sse import with_sse
import re
import sys
import json
import time
from lib.servo42c import *
from lib.stepper_doser_math import *
from config.pin_config import *
from lib.asyncscheduler import *
from time import localtime
from lib.cron_converter import Cron
from lib.sched.sched import schedule
import requests

try:
    # Micropython
    import gc
    import ota.status
    import ota.update
    import ota.rollback
    from machine import UART

    uart = UART(1)
    uart.init(baudrate=38400, rx=rx_pin, tx=tx_pin, timeout=100)
except ImportError:
    # Mocking on PC:
    from unittest.mock import Mock

    sys.implementation = Mock
    sys.implementation._machine = None

    ota = Mock()
    ota.status = Mock()
    ota.rollback.cancel = Mock(return_value=True)
    ota.status.current_ota = "<Partition type=0, subtype=16, address=65536, size=2555904, label=ota_0, encrypted=0>"
    ota.status.boot_ota = Mock(
        return_value="<Partition type=0, subtype=17, address=2621440, size=2555904, label=ota_1, encrypted=0>")

    gc = Mock()
    gc.mem_free = Mock(return_value=8000 * 1024)

    uart = Mock()
    uart.read = Mock(return_value=b"\xe0\x01\xe1")
    machine = Microdot
    machine.reset = Mock(return_value=True)

app = Microdot()
command_buffer = CommandBuffer()
task_manage = TaskManager(command_buffer)

PUMP_NUM = 9
EXTRAPOLATE_ANGLE = 4

rpm_table = make_rpm_table()
gc.collect()
ota_lock = False
ota_progress = 0
firmware_size = None

should_continue = True  # Flag for shutdown

with open("config/calibration_points.json", 'r') as read_file:
    calibration_points = json.load(read_file)

with open("config/analog_settings.json", 'r') as read_file:
    analog_settings = json.load(read_file)

mks_dict = {}
for stepper in range(1, PUMP_NUM + 1):
    mks_dict[f"mks{stepper}"] = Servo42c(uart, addr=stepper - 1, speed=1, mstep=50)
    mks_dict[f"mks{stepper}"].set_current(1000)

print(f"free memory: {gc.mem_free() // 1024}Kb")

with open("./config/wifi.json", 'r') as wifi_config:
    wifi_settings = json.load(wifi_config)
    ssid = wifi_settings["ssid"]
    password = wifi_settings["password"]


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


def get_points(from_json):
    if len(from_json) >= 2:
        _cal_points = []
        for point in from_json:
            _cal_points.append((point["rpm"], point["flowRate"]))
        return _cal_points
    else:
        return []


def get_analog_settings(from_json):
    if len(from_json) >= 2:
        _analog_points = []
        for point in from_json:
            print(point)
            _analog_points.append((point["analogInput"], point["flowRate"]))
        return _analog_points
    else:
        return []


chart_points = {}
for _ in range(1, PUMP_NUM + 1):
    cal_points = get_points(calibration_points[f"calibrationDataPump{_}"])
    if cal_points:
        print("----------------------")

        new_rpm_values, new_flow_rate_values = extrapolate_flow_rate(cal_points, degree=EXTRAPOLATE_ANGLE)
        print(new_flow_rate_values)
        print(new_flow_rate_values[-1])
        chart_points[f"pump{_}"] = (new_rpm_values, new_flow_rate_values)
        print("----------------------")

    else:
        chart_points[f"pump{_}"] = ([], [])

analog_chart_points = {}
analog_en = []
analog_pin = []
for _ in range(1, PUMP_NUM + 1):
    analog_en.append(analog_settings[f"pump{_}"]["enable"])
    analog_pin.append(analog_settings[f"pump{_}"]["pin"])
    analog_points = get_analog_settings(analog_settings[f"pump{_}"]["points"])
    print(analog_points)

    if analog_points and len(analog_points) >= 2:
        analog_chart_points[f"pump{_}"] = linear_interpolation(analog_points)
    else:
        analog_chart_points[f"pump{_}"] = ([], [])


def do_work(msg):
    print(localtime(), f" {msg}")


def schedule_work(manager, cron_expression, addr, volume, duration, direction):
    cron_instance = Cron()
    cron_instance.from_string(cron_expression)
    mins, hrs, mday, month, wday = cron_instance.to_list()

    desired_flow = volume * (60 / duration)
    desired_rpm_rate = np.interp(desired_flow, chart_points[f"pump{addr}"][1], chart_points[f"pump{addr}"][0])
    callback_result_future = CustomFuture()

    def callback(result):
        print(f"Callback received result: {result}")
        callback_result_future.set_result({"flow": desired_flow, "rpm": desired_rpm_rate[0], "time": result[0]})

    msg = f"Doser{addr} dose {volume} in {duration}sec"
    asyncio.create_task(schedule(do_work, msg,
                                 mins=mins,
                                 hrs=hrs,
                                 mday=mday,
                                 month=None,
                                 wday=wday
                                 ))
    """task = asyncio.create_task(schedule(command_buffer.add_command(stepper_run, callback, mks_dict[f"mks{addr}"],
                                                               desired_rpm_rate, duration, direction,
                                                               rpm_table), name,
                                         mins=mins,
                                         hrs=hrs,
                                         mday=mday,
                                         month=None,
                                         wday=wday),
                           name)"""


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
    gc.collect()
    print(f"free mem: {ret}Kb")
    return {"free_mem": ret}


@app.route('/favicon.ico')
async def apple_touch_icon(request):
    response = send_file('./static/favicon//favicon.ico')
    return response


@app.route('/apple-touch-icon.png')
async def apple_touch_icon(request):
    response = send_file('./static/favicon/apple-touch-icon.png')
    return response


@app.route('/favicon-16x16.png')
async def favicon_16(request):
    response = send_file('./static/favicon/favicon-16x16.png')
    return response


@app.route('/favicon-32x32.png')
async def favicon_32(request):
    response = send_file('./static/favicon/favicon-32x32.png')
    return response


@app.route('/site.webmanifest')
async def favicon_16(request):
    response = send_file('./static/favicon/site.webmanifest')
    return response


@app.route('/styles/<path:path>')
async def styles(request, path):
    if '..' in path:
        # directory traversal is not allowed
        return 'Not found', 404
    return send_file('static/styles/' + path)


@app.route('/javascript/<path:path>')
async def javascript(request, path):
    if '..' in path:
        # directory traversal is not allowed
        return 'Not found', 404
    return send_file('static/javascript/' + path)


@app.route('/static/<path:path>')
async def static(request, path):
    if '..' in path:
        # directory traversal is not allowed
        return 'Not found', 404
    return send_file('static/' + path)


@app.route('/run_with_rpm')
async def run_with_rpm(request):
    id = request.args.get('id', default=1, type=int)
    rpm = request.args.get('rpm', default=1, type=float)
    direction = request.args.get('direction', default=1, type=int)
    execution_time = request.args.get('time', default=1, type=float)

    print(f"[ID {id}] Run {rpm}RPM for {execution_time}sec Dir={direction}")

    callback_result_future = CustomFuture()

    def callback(result):
        print(f"Callback received result: {result}")
        callback_result_future.set_result({"time": result[0]})

    task = asyncio.create_task(
        command_buffer.add_command(stepper_run, callback, mks_dict[f"mks{id}"], rpm, execution_time, direction,
                                   rpm_table))
    await task

    await callback_result_future.wait()
    callback_result = await callback_result_future.wait()
    print("Result of callback:", callback_result)

    return callback_result


@app.route('/dose')
async def dose(request):
    id = request.args.get('id', default=1, type=int)
    volume = request.args.get('volume', default=0, type=float)
    execution_time = request.args.get('time', default=0, type=float)
    direction = request.args.get('direction', default=1, type=int)
    print(f"[Pump{id}]")
    print(f"Dose {volume}ml in {execution_time}s ")

    # Calculate RPM for Flow Rate
    desired_flow = volume * (60 / execution_time)
    print(f"Desired flow: {round(desired_flow, 2)}")
    print(f"Direction: {direction}")
    desired_rpm_rate = np.interp(desired_flow, chart_points[f"pump{id}"][1], chart_points[f"pump{id}"][0])

    callback_result_future = CustomFuture()

    def callback(result):
        print(f"Callback received result: {result}")
        callback_result_future.set_result({"flow": desired_flow, "rpm": desired_rpm_rate[0], "time": result[0]})

    task = asyncio.create_task(
        command_buffer.add_command(stepper_run, callback, mks_dict[f"mks{id}"], desired_rpm_rate, execution_time,
                                   direction, rpm_table))
    # await uart_buffer.process_commands()
    await task

    await callback_result_future.wait()
    callback_result = await callback_result_future.wait()
    print("Result of callback:", callback_result)

    return callback_result


@app.route('/', methods=['GET', 'POST'])
async def index(request):
    if request.method == 'GET':
        response = send_file('./static/doser.html')
        for _ in range(1, PUMP_NUM + 1):
            print(json.dumps(analog_settings[f"pump{_}"]))
            #response.set_cookie(f'AnalogInputDataPump{_}', json.dumps(analog_settings[f"pump{_}"]))
            response.set_cookie(f'AnalogPins', json.dumps(analog_pins))
        return response
    else:
        response = redirect('/')
        data = request.json
        print(data)
        for _ in range(1, PUMP_NUM + 1):
            if f"pump{_}" in data:
                if len(data[f"pump{_}"]["points"]) >= 2:
                    #response.set_cookie(f'AnalogInputDataPump{_}', json.dumps(data[f"pump{_}"]))

                    points = [(d['analogInput'], d['flowRate']) for d in data[f"pump{_}"]["points"]]
                    analog_chart_points[f"pump{_}"] = linear_interpolation(points)
                    print(analog_chart_points[f"pump{_}"])
                    # Save new settings
                    analog_settings[f"pump{_}"] = data[f"pump{_}"]

                else:
                    print(f"Pump{_} Not enough Analog Input points")
        with open("config/analog_settings.json", 'w') as write_file:
            write_file.write(json.dumps(analog_settings))
        return response


@app.route('/dose-chart-sse')
@with_sse
async def dose(request, sse):
    print("Got connection")
    old_chart_list = None
    try:
        while "eof" not in str(request.sock[0]):
            if old_chart_list != analog_chart_points or old_settings != analog_settings:
                old_chart_list = analog_chart_points
                old_settings = analog_settings
                event = json.dumps({
                    "AnalogChartPoints": old_chart_list,
                    "Settings": analog_settings,
                })

                print("send Analog Control settigs")
                await sse.send(event)  # unnamed event
                await asyncio.sleep(1)
            else:
                #print("No updates, skip")
                await asyncio.sleep(1)
    except Exception as e:
        print(f"Error in SSE loop: {e}")
    print("SSE closed")


@app.route('/debug', methods=['GET'])
async def debug(request):
    response = send_file('./static/debug.html')
    return response


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
        await asyncio.sleep(0.1)


@app.route('/ota-upgrade', methods=['GET', 'POST'])
async def ota_upgrade(request):
    if request.method == 'GET':
        global ota_lock
        response = send_file('./static/ota-upgrade.html')

        # Define a regular expression pattern to find "ota_" followed by digits
        pattern = r"ota_(\d+)"

        status = str(ota.status.current_ota)
        print(status)
        # Search for the pattern in the status string
        match = re.search(pattern, status)

        # Extract the ota_ number from the search result
        boot_partition = match.group(1) if match else None

        print(f"boot_partition= <{boot_partition}>")

        response.set_cookie(f'otaPartition', boot_partition)
        response.set_cookie(f'OtaStarted', ota_lock)
        version = sys.implementation._machine
        response.set_cookie(f'firmware', version)

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
                ota.update.from_file(filename, reboot=True)
                ota_lock = False

            except Exception as e:
                print("Error: ", e)
                ota_lock = False

        if cancel_rollback:
            print("Cancel firmware rollback")
            ota.rollback.cancel()

        response = 200

    return response


@app.route('/schedule', methods=['GET', 'POST'])
async def cron(request):
    if request.method == 'GET':
        schedule_work(task_manage, '*/3 * * * *', 1, 10, 60, 1)
    return 200


@app.route('/cron', methods=['GET', 'POST'])
async def cron(request):
    if request.method == 'GET':
        response = send_file('./static/cron.html')
    else:
        data = request.json
        print("Got POST", data)
        response = redirect('/cron')
    return response


@app.route('/calibration', methods=['GET', 'POST'])
async def calibration(request):
    if request.method == 'GET':
        response = send_file('./static/calibration.html')
        for pump in range(1, PUMP_NUM + 1):
            response.set_cookie(f'calibrationDataPump{pump}',
                                json.dumps(calibration_points[f"calibrationDataPump{pump}"]))
    else:
        response = redirect('/')
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
    return response


@app.route('/settings', methods=['GET', 'POST'])
async def settings(request):
    if request.method == 'GET':
        response = send_file('./static/captive_portal.html')
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


@app.route('/wifi_settings', methods=['GET', 'POST'])
async def wifi_settings(request):
    print("Got connection")
    if request.method == 'GET':
        response = send_file('./static/captive_portal.html')
        response.set_cookie(f'current_ssid', ssid)

    else:
        new_ssid = request.json[f"ssid"]
        new_psw = request.json[f"psw"]
        with open("./config/wifi.json", "w") as f:
            f.write(json.dumps({"ssid": new_ssid, "password": new_psw}))
        print(f"Setting up new wifi {new_ssid}, Reboot...")
        sys.exit()
    return response


import os

print(os.listdir('./static/'))

asyncio.create_task((app.run(port=80)))
