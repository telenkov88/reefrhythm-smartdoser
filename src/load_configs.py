import json
from lib.stepper_doser_math import *
from lib.servo42c import *
from lib.asyncscheduler import *
from config.pin_config import *
import array
import struct
try:
    import gc
    import utime
    from machine import UART, Pin, ADC, unique_id
    import network
    import machine
    import asyncio

    # Use modified ntptime with timezone support
    import lib.ntptime as ntptime
    import time

    uart = UART(1)
    uart.init(baudrate=38400, rx=rx_pin, tx=tx_pin, timeout=100)
    wifi = network.WLAN(network.STA_IF)

    # unique id:
    import ubinascii
    unique_id = ubinascii.hexlify(unique_id()).decode('ascii')
    web_compress = True
    web_file_extension = ".gz"

except ImportError:
    print("import_config debugging on PC")
    # Mocking ADC
    from unittest.mock import Mock, MagicMock
    import asyncio
    mac_address = "AA:AA:BB:BB:AA:AA"
    network = MagicMock()
    wifi = network.WLAN(network.STA_IF)
    wifi.config.return_value = b'\xde\xad\xbe\xef\xca\xfe'

    ADC = Mock()
    Pin = Mock()
    ntptime = Mock()

    unique_id = 'aaaabbbb'

    Pin.return_value = Mock()
    mock_adc = Mock()
    ubinascii = Mock()

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
EXTRAPOLATE_ANGLE = 4


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

# General device settings
try:
    with open("config/settings.json", 'r') as read_file:
        settings = json.load(read_file)
except Exception as e:
    print("Can't load general setting config, load default ", e)
    settings = {"pump_number": 1, "hostname": "doser", "timezone": 0.0, "timeformat": 0, "ntphost": "time.google.com",
                "analog_period": 60,
                "pumps_current": [1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000],
                "inversion": [0, 0, 0, 0, 0, 0, 0, 0, 0],
                "names": ["Pump 1", "Pump 2", "Pump 3", "Pump 4", "Pump 5", "Pump 6", "Pump 7", "Pump 8", "Pump 9"],
                "color": "dark",
                "theme": "cerulean"}

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

if "pumps_current" not in settings:
    pumps_current = [1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000]
else:
    pumps_current = settings["pumps_current"]
if "analog_period" not in settings:
    analog_period = 60
else:
    analog_period = settings["analog_period"]

if "inversion" not in settings:
    inversion = [0, 0, 0, 0, 0, 0, 0, 0, 0]
else:
    inversion = settings["inversion"]
if "names" not in settings:
    pump_names = ["Pump 1", "Pump 2", "Pump 3", "Pump 4", "Pump 5", "Pump 6", "Pump 7", "Pump 8", "Pump 9"]
else:
    pump_names = settings["names"]
if "color" not in settings:
    color = "dark"
else:
    color = settings["color"]
if "theme" not in settings:
    theme = "cerulean"
else:
    theme = settings["theme"]

if "whatsapp_number" not in settings:
    whatsapp_number = ""
else:
    whatsapp_number = settings["whatsapp_number"]

if "whatsapp_apikey" not in settings:
    whatsapp_apikey = ""
else:
    whatsapp_apikey = settings["whatsapp_apikey"]

if "telegram" not in settings:
    telegram = ""
else:
    telegram = settings["telegram"]

if "empty_container_msg" not in settings:
    empty_container_msg = 0
else:
    empty_container_msg = settings["empty_container_msg"]

if "empty_container_lvl" not in settings:
    empty_container_lvl = 0
else:
    empty_container_lvl = settings["empty_container_lvl"]

if "dose_msg" not in settings:
    dose_msg = 0
else:
    dose_msg = settings["dose_msg"]


PUMP_NUM = settings["pump_number"]


# Storage count configs
try:
    with open("config/storage.json") as read_file:
        storage = json.load(read_file)
        print("storage: ", storage)
except Exception as e:
    print("Can't load storage config, generate new")
    storage = {}
    for _ in range(1, MAX_PUMPS+1):
        storage[f"pump{_}"] = 0
        storage[f"remaining{_}"] = 0
    with open('config/storage.json', 'w') as write_file:
        json.dump(storage, write_file)
for _ in range(1, MAX_PUMPS+1):
    if f"pump{_}" not in storage:
        storage[f"pump{_}"] = 0
    if f"remaining{_}" not in storage:
        storage[f"remaining{_}"] = 0

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
    mks_dict[f"mks{stepper}"].set_current(pumps_current[stepper-1])

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

try:
    with open("./config/mqtt.json", 'r') as mqtt_config:
        mqtt_settings = json.load(mqtt_config)
        if "broker" in mqtt_settings:
            mqtt_broker = mqtt_settings["broker"]
        else:
            mqtt_broker = ""
        if "login" in mqtt_settings:
            mqtt_login = mqtt_settings["login"]
        else:
            mqtt_login = ""
        if "password" in mqtt_settings:
            mqtt_password = mqtt_settings["password"]
        else:
            mqtt_password = ""
except Exception as e:
    print("\nfailed to load config/mqtt.json, ", e)
    mqtt_broker = ""
    mqtt_login = ""
    mqtt_password = ""


limits_dict = {}
try:
    with open("./config/limits.json", 'r') as limits_config:
        limits_settings = json.load(limits_config)
        for _ in range(1, MAX_PUMPS + 1):
            if f"{_}" in limits_settings:
                limits_dict[_] = limits_settings[f"{_}"]
            else:
                limits_dict[_] = "True"

except Exception as e:
    print("\nfailed to load ./config/limits.json, ", e)
    for _ in range(1, MAX_PUMPS + 1):
        limits_dict[_] = "True"

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


def load_files_to_ram(directory, filenames, pattern):
    # Dictionary to store the content of files
    files_content = {}
    # Manually specified list of filenames to load
    for filename in filenames:
        # Check if the filename ends with pattern
        full_path = directory + '/' + filename + pattern

        # Open the file
        with open(full_path, 'rb') as f:
            # Read the file content
            content = f.read()

        # Store the content in the dictionary
        files_content[filename] = content

    return files_content