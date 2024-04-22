import json
import binascii
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

    # Use modified ntptime with timezone support
    import lib.ntptime as ntptime
    import time

    ap = network.WLAN(network.AP_IF)
    nic = network.WLAN(network.STA_IF)
    ap = network.WLAN(network.AP_IF)
    byte_string = nic.config('mac')
    hex_string = binascii.hexlify(byte_string).decode('utf-8')
    mac_address = ':'.join(hex_string[i:i+2] for i in range(0, len(hex_string), 2)).upper()
    uart = UART(1)
    uart.init(baudrate=38400, rx=rx_pin, tx=tx_pin, timeout=100)
except ImportError:
    # Mocking ADC
    from unittest.mock import Mock

    mac_address = "AA:AA:BB:BB:AA:AA"

    ADC = Mock()
    Pin = Mock()
    ntptime = Mock()
    nic = Mock
    nic.isconnected = Mock(return_value=False)

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


with open("config/calibration_points.json", 'r') as read_file:
    calibration_points = json.load(read_file)

with open("config/analog_settings.json", 'r') as read_file:
    analog_settings = json.load(read_file)

with open("config/settings.json", 'r') as read_file:
    settings = json.load(read_file)
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


PUMP_NUM = settings["pump_number"]
MAX_PUMPS = 9

try:
    with open("config/schedule.json") as read_file:
        schedule = json.load(read_file)
        print("schedule: ", schedule)
except OSError as e:
    print("Can't load schedule config, generate new")
    schedule = {}
    for _ in range(1, MAX_PUMPS+1):
        schedule[f"pump{_}"] = []

mks_dict = {}
for stepper in range(1, PUMP_NUM + 1):
    mks_dict[f"mks{stepper}"] = Servo42c(uart, addr=stepper - 1, speed=1, mstep=50)
    mks_dict[f"mks{stepper}"].set_current(1000)

try:
    with open("./config/wifi.json", 'r') as wifi_config:
        wifi_settings = json.load(wifi_config)
        ssid = wifi_settings["ssid"]
        password = wifi_settings["password"]
except OSError as e:
    ssid = "test"
    password = "test"

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
