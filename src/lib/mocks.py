print("Mocking on PC")
from unittest.mock import Mock, MagicMock
import random
import time


RELEASE_TAG = "local_debug"
from unittest.mock import MagicMock
import random

unique_id = MagicMock()
unique_id.return_value = "aabbbccdd".encode()

net = MagicMock()
net.ifconfig = MagicMock()
net.ifconfig.return_value = ["127.0.0.1"]

gc = Mock()
gc.collect = Mock()
gc.mem_free = Mock(return_value=8000 * 1024)
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

network = MagicMock()
network.WLAN = MagicMock()
network.WLAN.ifconfig = Mock(return_value='127.0.0.1')
wifi = network.WLAN(network.STA_IF)
ap = network.WLAN()
wifi.config.return_value = b'\xde\xad\xbe\xef\xca\xfe'
ADC = Mock()
Pin = Mock()
ntptime = Mock()
utime = Mock()

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


# Dummy decorator to simulate @micropython.native
# Creating a more structured mock for micropython module
class Micropython:
    @staticmethod
    def native(func):
        # Decorator that simply returns the function unchanged
        return func


# Assign the mock class to a variable with the module's name
micropython = Micropython()


def random_adc_read():
    import random
    return random.randint(800, 1000)


ntptime = Mock()
ADC = Mock()
Pin = Mock()
mock_adc = Mock()
mock_adc.read.side_effect = random_adc_read
ADC.return_value = mock_adc
mcron = Mock
mcron.remove_all = Mock()
mcron.insert = Mock()
mcron.init_timer = Mock()


class MQTTClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        print(f"MQTT Client initialized with parameters: {kwargs}")

    def log(self):
        exc = f"MQTT Exception ({random.randint(0, 10)})"
        print(exc)
        return exc

    def set_callback(self, callback):
        self.callback = callback
        print("Callback has been set.")

    def set_last_will(self, topic, message, retain):
        print(f"Set last will: topic='{topic}', message='{message}', retain={retain}")

    def connect(self):
        print("Connected to MQTT broker.")

    def reconnect(self):
        print("Reconnect to MQTT broker.")
        return True

    def subscribe(self, topic):
        print(f"Subscribed to topic: {topic}")

    def resubscribe(self):
        print(f"Resubscribe to topics")

    def publish(self, topic, payload, retain):
        print(f"Mock publish to {topic}: {payload}. Retain {retain}")

    def check_msg(self):
        # Simulate incoming messages if needed
        pass

    def disconnect(self):
        print("Disconnected from MQTT broker.")

    def is_conn_issue(self):
        if random.randint(1, 10) < 3:
            return True
        return False
