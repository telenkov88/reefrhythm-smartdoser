from unittest.mock import MagicMock
import random

unique_id = MagicMock()
unique_id.return_value = "aabbbccdd".encode()

net = MagicMock()
net.ifconfig = MagicMock()
net.ifconfig.return_value = ["127.0.0.1"]


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


class CommandHandler:
    def __init__(self, command_buffer):
        print()

    def dose(self, command):
        print(f"Handling dosing command: {command}")

    def run(self, command):
        print(f"Handling run command: {command}")

    def stop(self, command):
        print(f"Handling stop command: {command}")

    def refill(self, command):
        print(f"Handling refill command: {command}")