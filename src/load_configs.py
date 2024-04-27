import json
from lib.stepper_doser_math import *
from lib.servo42c import *
from lib.asyncscheduler import *

EXTRAPOLATE_ANGLE = 4
from config.pin_config import *

try:
    import gc
    import utime
    from machine import UART, Pin, ADC
    import network
    import machine
    import asyncio

    # Use modified ntptime with timezone support
    import lib.ntptime as ntptime
    import time

    uart = UART(1)
    uart.init(baudrate=38400, rx=rx_pin, tx=tx_pin, timeout=100)
except ImportError:
    print("import_config debugging on PC")
    # Mocking ADC
    from unittest.mock import Mock
    import asyncio
    mac_address = "AA:AA:BB:BB:AA:AA"
    network = Mock()

    ADC = Mock()
    Pin = Mock()
    ntptime = Mock()


    Pin.return_value = Mock()
    mock_adc = Mock()

    utime = Mock()
    import time
    # Utime is CPython epoch 2000-01-01 00:00:00 UTC, when time.time() is 1970-01-01 00:00:00 UTC epoch
    utime.time = Mock(return_value=(time.time()-946684800))


    def localtime():
        import datetime
        return datetime.datetime.now().strftime("%Y %m %d %H %M %S").split()


    utime.localtime = localtime

    def random_adc_read():
        import random
        return random.randint(800, 1000)


    mock_adc.read.side_effect = random_adc_read
    ADC.return_value = mock_adc

    uart = Mock()
    uart.read = Mock(return_value=b"\xe0\x01\xe1")

    sys = Mock()
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

    machine = Mock()
    machine.reset = Mock(return_value=True)
    web_compress = False
    web_file_extension = ""

MAX_PUMPS = 9


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


def get_time():
    _time = utime.localtime()
    print(_time)
    return f"{_time[3]:02}:{_time[4]:02}:{_time[5]:02}"


# Settings for Calibration
try:
    with open("config/calibration_points.json", 'r') as read_file:
        calibration_points = json.load(read_file)
except Exception as e:
    print("Can't load calibration config, load default ", e)
    calibration_points = {}
    for _ in range(MAX_PUMPS):
        if f"calibrationDataPump{_ + 1}" not in calibration_points:
            calibration_points[f"calibrationDataPump{_ + 1}"] = [{"rpm": 100,"flowRate": 100},{"rpm": 500,"flowRate": 400},{"rpm": 1000,"flowRate": 800}]


# Settings for Analog control
try:
    with open("config/analog_settings.json", 'r') as read_file:
        analog_settings = json.load(read_file)
        if "period" not in analog_settings:
            analog_settings[f"period"] = 60
        for _ in range(MAX_PUMPS):
            if f"pump{_+1}" not in analog_settings:
                analog_settings[f"pump{_ + 1}"] = {"enable": False, "pin": 99, "dir": 1,
                                                   "points": [{"analogInput": 0, "flowRate": 0},
                                                              {"analogInput": 100, "flowRate": 5}]}


except Exception as e:
    print("Can't load analog setting config, load default ", e)
    analog_settings = {}
    for _ in range(MAX_PUMPS):
        analog_settings[f"pump{_+1}"] = {"enable": False, "pin": 99, "dir": 1, "points": [{"analogInput": 0, "flowRate": 0}, {"analogInput": 100, "flowRate": 5}]}
        analog_settings[f"period"] = 60


# General device settings
try:
    with open("config/settings.json", 'r') as read_file:
        settings = json.load(read_file)
except Exception as e:
    print("Can't load general setting config, load default ", e)
    settings = {"pump_number": 1, "hostname": "doser", "timezone": 0.0, "timeformat": 0, "ntphost": "time.google.com"}

if "hostname" not in settings:
    hostname = "doser"
else:
    hostname = settings["hostname"]
if "timezone" not in settings:
    timezone = 0.0
else:
    timezone = settings["timezone"]
if "timeformat" not in settings:
    timeformat = 0
else:
    timeformat = settings["timeformat"]

if "ntphost" not in settings:
    ntphost = "time.google.com"
else:
    ntphost = settings["ntphost"]

PUMP_NUM = settings["pump_number"]

try:
    with open("config/schedule.json") as read_file:
        schedule = json.load(read_file)
        print("schedule: ", schedule)
except Exception as e:
    print("Can't load schedule config, generate new")
    schedule = {}
    for _ in range(1, MAX_PUMPS+1):
        schedule[f"pump{_}"] = []

mks_dict = {}
for stepper in range(1, PUMP_NUM + 1):
    mks_dict[f"mks{stepper}"] = Servo42c(uart, addr=stepper - 1, speed=1)
    mks_dict[f"mks{stepper}"].set_current(1000)

try:
    with open("./config/wifi.json", 'r') as wifi_config:
        wifi_settings = json.load(wifi_config)
        if "ssid" in wifi_settings:
            ssid = wifi_settings["ssid"]
        else:
            ssid = ""
        if "password" in wifi_settings:
            password = wifi_settings["password"]
        else:
            password = ""
except Exception as e:
    print("Failed to load config/wifi.json ", e)
    ssid = ""
    password = ""


chart_points = {}
for _ in range(1, MAX_PUMPS + 1):
    cal_points = get_points(calibration_points[f"calibrationDataPump{_}"])
    if cal_points and _ <= PUMP_NUM:
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
for _ in range(1, MAX_PUMPS + 1):
    analog_en.append(analog_settings[f"pump{_}"]["enable"])
    analog_pin.append(analog_settings[f"pump{_}"]["pin"])
    analog_points = get_analog_settings(analog_settings[f"pump{_}"]["points"])
    print(analog_points)

    if analog_points and len(analog_points) >= 2:
        analog_chart_points[f"pump{_}"] = linear_interpolation(analog_points)
    else:
        analog_chart_points[f"pump{_}"] = ([], [])


rpm_table = make_rpm_table()
command_buffer = CommandBuffer()
