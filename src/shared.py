import json
from lib.config_defaults import *
from config.pin_config import rx_pin, tx_pin, analog_pins
from unittest.mock import Mock, MagicMock
from lib.servo42c import Servo42c
from lib.stepper_doser_math import extrapolate_flow_rate, linear_interpolation
try:
    import gc
    import utime
    from machine import UART, Pin, ADC, unique_id
    import network
    import machine
    import asyncio
    import lib.ntptime as ntptime
    import time

    uart = UART(1)
    uart.init(baudrate=38400, rx=rx_pin, tx=tx_pin, timeout=100)
    wifi = network.WLAN(network.STA_IF)
    import ubinascii

    unique_id = ubinascii.hexlify(unique_id()).decode('ascii')
    web_compress = True
    web_file_extension = ".gz"

except ImportError:
    print("import_config debugging on PC")
    network = MagicMock()
    wifi = network.WLAN(network.STA_IF)
    wifi.config.return_value = b'\xde\xad\xbe\xef\xca\xfe'
    ADC = Mock()
    Pin = Mock()
    ntptime = Mock()
    unique_id = 'aaaabbbb'
    utime = Mock()
    import time

    utime.time = Mock(return_value=(time.time() - 946684800))


    def localtime():
        import datetime
        return datetime.datetime.now().strftime("%Y %m %d %H %M %S").split()


    utime.localtime = localtime


    def random_adc_read():
        import random
        return random.randint(800, 1000)


    mock_adc = Mock()
    mock_adc.read.side_effect = random_adc_read
    ADC.return_value = mock_adc

    uart = Mock()
    uart.read = Mock(return_value=b"\xe0\x01\xe1")
    gc = Mock()
    gc.mem_free = Mock(return_value=8000 * 1024)
    machine = Mock()
    machine.reset = Mock(return_value=True)
    web_compress = False
    web_file_extension = ""

MAX_PUMPS = 9
EXTRAPOLATE_ANGLE = 4

adc_sampler_started = False


def get_points(from_json):
    return [(point["rpm"], point["flowRate"]) for point in from_json if len(from_json) >= 2]


def get_analog_settings(from_json):
    return [(point["analogInput"], point["flowRate"]) for point in from_json if len(from_json) >= 2]


def get_time():
    _time = utime.localtime()
    return f"{_time[3]:02}:{_time[4]:02}:{_time[5]:02}"


calibration_points = {}
try:
    with open("config/calibration_points.json", 'r') as file:
        calibration_points = json.load(file)
except Exception as e:
    print("Can't load calibration config ", e)
check_defaults_calibration(calibration_points, MAX_PUMPS)

analog_settings = {}
try:
    with open("config/analog_settings.json", 'r') as file:
        analog_settings = json.load(file)
except Exception as e:
    print("Can't load analog settings config ", e)
check_defaults_analog_settings(analog_settings, MAX_PUMPS)

settings = {}
try:
    with open("config/settings.json", 'r') as file:
        settings = json.load(file)
except Exception as e:
    print("Can't load general settings config ", e)

check_defaults_settings(settings)

storage = {}
try:
    with open("config/storage.json") as file:
        storage = json.load(file)
except Exception as e:
    print("Can't load storage config", e)

check_defaults_storage(storage, MAX_PUMPS)

schedule = {}
try:
    with open("config/schedule.json") as file:
        schedule = json.load(file)
except Exception as e:
    print("Can't load schedule config ", e)

check_defaults_schedule(schedule, MAX_PUMPS)

mqtt_settings = {}
try:
    with open("config/mqtt.json", 'r') as file:
        mqtt_settings = json.load(file)
except Exception as e:
    print("Failed to load MQTT settings ", e)
check_defaults_mqtt(mqtt_settings)


limits_settings = {}
try:
    with open("config/limits.json", 'r') as file:
        limits_settings = json.load(file)
except Exception as e:
    print("Failed to load limits settings ", e)
check_defaults_limits(limits_settings, MAX_PUMPS)


PUMP_NUM = settings["pump_number"]

chart_points = {}
for _ in range(1, MAX_PUMPS + 1):
    cal_points = get_points(calibration_points[f"calibrationDataPump{_}"])
    if cal_points and _ <= PUMP_NUM:
        new_rpm_values, new_flow_rate_values = extrapolate_flow_rate(cal_points, degree=EXTRAPOLATE_ANGLE)
        chart_points[f"pump{_}"] = (new_rpm_values, new_flow_rate_values)
    else:
        chart_points[f"pump{_}"] = ([], [])


analog_chart_points = {}
analog_en = []
analog_pin = []

for _ in range(1, MAX_PUMPS + 1):
    analog_en.append(analog_settings[f"pump{_}"]["enable"])
    analog_pin.append(analog_settings[f"pump{_}"]["pin"])
    analog_points = get_analog_settings(analog_settings[f"pump{_}"]["points"])
    if analog_points and len(analog_points) >= 2:
        analog_chart_points[f"pump{_}"] = linear_interpolation(analog_points)
    else:
        analog_chart_points[f"pump{_}"] = ([], [])


def load_files_to_ram(directory, filenames, pattern):
    files_content = {}
    for filename in filenames:
        full_path = f"{directory}/{filename}{pattern}"
        try:
            with open(full_path, 'rb') as file:
                files_content[filename] = file.read()
        except Exception as e:
            print(f"Failed to load {full_path}: {e}")
    return files_content


mks_dict = {}
for stepper in range(1, PUMP_NUM + 1):
    mks_dict[f"mks{stepper}"] = Servo42c(uart, addr=stepper - 1, speed=1)
    mks_dict[f"mks{stepper}"].set_current(settings["pumps_current"][stepper-1])


ssid = ""
password = ""
try:
    with open("./config/wifi.json", 'r') as wifi_config:
        wifi_settings = json.load(wifi_config)
        if "ssid" in wifi_settings:
            ssid = wifi_settings["ssid"]
        if "password" in wifi_settings:
            password = wifi_settings["password"]
except Exception as e:
    print("Failed to load config/wifi.json ", e)
