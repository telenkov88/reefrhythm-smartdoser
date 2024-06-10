from unittest.mock import Mock, MagicMock
import time
import random
RELEASE_TAG = "local_debug"
web_compress = False
web_file_extension = ""

unique_id = MagicMock()
unique_id.return_value = bytes.fromhex('aaaaBBBB')

mqtt_id = unique_id()
print(mqtt_id)

sys = Mock()
sys.implementation = Mock
sys.implementation._machine = None

# OTA Mocks
ota = Mock()
ota.status = Mock()
ota.rollback.cancel = Mock(return_value=True)
ota.status.current_ota = "<Partition type=0, subtype=16, address=65536, size=2555904, label=ota_0, encrypted=0>"
ota.status.boot_ota = Mock(
    return_value="<Partition type=0, subtype=17, address=2621440, size=2555904, label=ota_1, encrypted=0>")

# Network Mocks
network = MagicMock()
network.WLAN = MagicMock()
network.WLAN.ifconfig = Mock(return_value='127.0.0.1')
net = network
wifi = network.WLAN(network.STA_IF)
ap = network.WLAN()
wifi.config.return_value = b'\xde\xad\xbe\xef\xca\xfe'

utime = Mock()
utime.time = Mock(return_value=(time.time() - 946684800))

# Machine Mocks #
gc = Mock()
gc.mem_free = Mock(return_value=8000 * 1024)
gc.collect = Mock()
machine = Mock()
machine.reset = Mock(return_value=True)

Pin = Mock()
uart = Mock()
uart.read = Mock(return_value=b"\xe0\x01\xe1")


def random_adc_read():
    import random
    return random.randint(800, 1000)


ADC = Mock()
mock_adc = Mock()
mock_adc.read.side_effect = random_adc_read
ADC.return_value = mock_adc


# Time Mocks
def localtime():
    import datetime
    return datetime.datetime.now().strftime("%Y %m %d %H %M %S").split()


ntptime = Mock()
utime.localtime = localtime
mcron = Mock
mcron.remove_all = Mock()
mcron.insert = Mock()
mcron.init_timer = Mock()


def ticks_us():
    """Return the current time in microseconds."""
    return int(time.time() * 1_000_000)


def ticks_diff(a, b):
    """Calculate the difference in microseconds between two timestamps."""
    return a - b


class MQTTClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.callback = None
        print(f"MQTT Client initialized with parameters: {kwargs}")

    @staticmethod
    def log():
        exc = f"MQTT Exception ({random.randint(0, 10)})"
        print(exc)
        return exc

    def set_callback(self, callback):
        self.callback = callback
        print("Callback has been set.")

    @staticmethod
    def set_last_will(topic, message, retain):
        print(f"Set last will: topic='{topic}', message='{message}', retain={retain}")

    @staticmethod
    def connect():
        print("Connected to MQTT broker.")

    @staticmethod
    def reconnect():
        print("Reconnect to MQTT broker.")
        return True

    @staticmethod
    def subscribe(topic):
        print(f"Subscribed to topic: {topic}")

    @staticmethod
    def resubscribe():
        print(f"Resubscribe to topics")

    @staticmethod
    def publish(topic, payload, retain):
        print(f"Mock publish to {topic}: {payload}. Retain {retain}")

    def check_msg(self):
        # Simulate incoming messages if needed
        pass

    @staticmethod
    def disconnect():
        print("Disconnected from MQTT broker.")

    @staticmethod
    def is_conn_issue():
        if random.randint(1, 10) < 3:
            return True
        return False


# Dummy decorators to simulate @micropython code emitters
class Micropython:
    @staticmethod
    def native(func):
        return func

    @staticmethod
    def viper(func):
        return func


# @micropython.viper specific data types
class MockPtr8:
    def __init__(self, data):
        self.data = data

    def __getitem__(self, index):
        return self.data[index]

    def __setitem__(self, index, value):
        self.data[index] = value


class MockPtr16:
    def __init__(self, data):
        self.data = data

    def __getitem__(self, index):
        return self.data[index]

    def __setitem__(self, index, value):
        self.data[index] = value



class MockPtr32:
    def __init__(self, data):
        self.data = data

    def __getitem__(self, index):
        return self.data[index]

    def __setitem__(self, index, value):
        self.data[index] = value


ptr8 = MockPtr8
ptr16 = MockPtr16
ptr32 = MockPtr32
uint = int

# Assign the mock class to a variable with the module's name
micropython = Micropython()
