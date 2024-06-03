from unittest.mock import MagicMock

unique_id = MagicMock()
unique_id.return_value = "aabbbccdd".encode()


class MQTTClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        print(f"MQTT Client initialized with parameters: {kwargs}")

    def set_callback(self, callback):
        self.callback = callback
        print("Callback has been set.")

    def set_last_will(self, topic, message, retain):
        print(f"Set last will: topic='{topic}', message='{message}', retain={retain}")

    def connect(self):
        print("Connected to MQTT broker.")

    def subscribe(self, topic):
        print(f"Subscribed to topic: {topic}")

    def publish(self, topic, payload):
        print(f"Mock publish to {topic}: {payload}")

    def check_msg(self):
        # Simulate incoming messages if needed
        pass

    def disconnect(self):
        print("Disconnected from MQTT broker.")