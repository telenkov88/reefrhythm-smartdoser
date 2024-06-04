import json
try:
    import gc
    from lib.umqtt.robust2 import MQTTClient
    from lib.async_queue import Queue as asyncQueue
    import ubinascii
    from machine import unique_id
    from release_tag import *
except ImportError:
    from lib.mocks import MQTTClient, unique_id, net
    from asyncio import Queue as asyncQueue
    import binascii as ubinascii

    RELEASE_TAG = "debug version"

import asyncio

unique_id = ubinascii.hexlify(unique_id()).decode('ascii')

topics = {
    'status': 'status',
    'subscriptions': ['dose', 'run', 'stop', 'refill'],
}


def mqtt_stats(**kwargs):
    return {
        "version": kwargs['version'],
        "hostname": kwargs['hostname'],
        "settings": json.dumps({
            "names": kwargs['names'],
            "number": kwargs['number'],
            "current": kwargs['current'],
            "inversion": kwargs['inversion'],
            "storage": [kwargs['storage'][f"pump{x}"] for x in range(1, kwargs['max_pumps'] + 1)]
        })
    }


class MQTTWorker:
    def __init__(self, client_params, stats, command_handler, network):
        self.service = True
        if not client_params["server"]:
            print("Initialization Error: No server provided.")
            self.service = False
            return

        self.client = MQTTClient(**client_params)  # Initialize the MQTT client
        self.base_topic = f"/{client_params['client_id'].replace('-', '/')}/"
        print(self.base_topic)
        self.topics = topics
        self.stats = stats
        self.command_handler = command_handler
        self.net = network

        self.mqtt_publish_queue = asyncQueue()
        self.setup_client()
        self.connected = True
        print(f"Service initialized at {self.base_topic}")

    def setup_client(self):
        self.client.set_callback(self.on_message)
        self.client.set_last_will(self.base_topic + self.topics['status'], 'Disconnected', retain=True)

    async def worker(self):
        if not self.service:
            return

        while not self.net.isconnected():
            await asyncio.sleep(1)
        try:
            self.client.connect()
        except Exception as e:
            print("MQTT error, ", e)
            self.connected = False
        for topic in self.topics['subscriptions']:
            self.client.subscribe(self.base_topic + topic)

        self.client.subscribe("$SYS/broker/uptime")  # Service subscription to keep connection alive
        self.publish_stats()
        self.add_message_to_publish(self.topics['status'], "Connected", retain=True)

        tasks = [
            asyncio.create_task(self.handle_incoming_messages()),
            asyncio.create_task(self.publish())
        ]
        await asyncio.sleep(15)  # Await first service message
        while True:
            issue = self.client.is_conn_issue()
            if issue or not self.connected:
                log = self.client.log()
                print(f"log: {log}, issue: {issue}")

                print(f"MQTT Connection issue detected, MQTT attempting to reconnect...")
                if not self.net.isconnected():
                    print("MQTT wait for network connection")
                while not self.net.isconnected():
                    await asyncio.sleep(1)
                try:
                    self.client.reconnect()
                    await asyncio.sleep(5)
                    if self.client.is_conn_issue():
                        print("MQTT reconnect failed")
                        self.client.log()
                    else:
                        print("MQTT reconnect success")
                        self.connected = True
                        self.add_message_to_publish(self.topics['status'], "Connected", retain=True)
                        self.client.resubscribe()
                        self.publish_stats()

                except Exception as e:
                    print("MQTT Error: ", e)
                    self.connected = False
            await asyncio.sleep(20)

    async def handle_incoming_messages(self):
        while self.connected and self.service:
            self.client.check_msg()
            await asyncio.sleep(1)

    async def publish(self):
        while self.connected and self.service:
            message = await self.mqtt_publish_queue.get()
            if message:
                self.client.publish(message['topic'], message['payload'], retain=message['retain'])
                print(f'Published to {message["topic"]}: {message["payload"]}')
                self.mqtt_publish_queue.task_done()

    def publish_stats(self, new_stats=None):
        if self.service:
            if new_stats is not None:
                print("MQTT Update stats: ", new_stats)
                self.stats = new_stats
            self.add_message_to_publish("ip", "" + self.net.ifconfig()[0], retain=True)
            for _topic in self.stats:
                if "pump" in _topic:
                    self.add_message_to_publish(_topic, self.stats[_topic], retain=False)
                else:
                    self.add_message_to_publish(_topic, self.stats[_topic], retain=True)

    def add_message_to_publish(self, topic, data, retain=False):
        if self.service:
            message = {'topic': self.base_topic + topic, 'payload': data, 'retain': retain}
            print(f"MQTT add message {message}")
            asyncio.create_task(self.mqtt_publish_queue.put(message))

    def decode_body(self, msg):
        try:
            print("MQTT decode message: ", msg.decode('ascii'))
            mqtt_body = json.loads(msg.decode('ascii'))
            print(mqtt_body)
            return mqtt_body
        except Exception as mqtt_decode_e:
            print(f"Failed to decode mqtt message: {msg}, ", mqtt_decode_e)
        return False

    def on_message(self, topic, msg, retain, dup):
        _topic = topic.decode()
        print(f'Received message on topic: {_topic} with message: {msg.decode()}')
        if _topic.split("/")[-1] in self.topics['subscriptions']:
            message = self.decode_body(msg)
            if message:
                self.process_command(_topic.split("/")[-1], message)

    def process_command(self, topic, command):
        print(f"MQTT process command, {topic}, {command}")
        if topic == 'dose':
            asyncio.create_task(self.command_handler.dose(command))
        elif topic == 'run':
            asyncio.create_task(self.command_handler.run(command))
        elif topic == 'stop':
            asyncio.create_task(self.command_handler.stop(command))
        elif topic == 'refill':
            asyncio.create_task(self.command_handler.refill(command))
        print("MQTT process command finish")


async def main():
    try:
        import json
        # {"login": "login", "password": "password", "broker": "broker ip"}
        with open("./config/mqtt.json", 'r') as read_file:
            settings = json.load(read_file)
            user = settings["login"]
            password = settings["password"]
            broker = settings["broker"]
            print(f"Using broker {broker} with user {user}")
    except OSError:
        user = "mqtt"
        password = "mqtt"
        broker = "localhost"

    client_params = {'client_id': "ReefRhythm-" + unique_id,
                     'server': broker, 'port': 1883, 'user': user, 'password': password}

    stats = {"version": "debug_version", "hostname": "localhost"}
    from lib.pump_control import CommandHandler
    command_handler = CommandHandler()
    mqtt_worker = MQTTWorker(client_params, stats, command_handler, net)
    asyncio.create_task(mqtt_worker.worker())
    await asyncio.sleep(1)
    for i in range(10):
        mqtt_worker.add_message_to_publish("test", f"Msg No{i}")
    await asyncio.sleep(120)


if __name__ == '__main__':
    asyncio.run(main())
