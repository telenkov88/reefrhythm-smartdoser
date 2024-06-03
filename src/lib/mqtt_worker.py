import json
from lib.asyncscheduler import CommandHandler
try:
    import gc
    from lib.umqtt.robust2 import MQTTClient
    from lib.async_queue import Queue as asyncQueue
    import ubinascii
    from machine import unique_id
except ImportError:
    from lib.mocks import MQTTClient, unique_id
    from asyncio import Queue as asyncQueue
    import binascii as ubinascii

import asyncio

unique_id = ubinascii.hexlify(unique_id()).decode('ascii')


class MQTTWorker:
    def __init__(self, client_params, topics, command_handler):
        self.service = True
        if not client_params["server"]:
            print("Initialization Error: No server provided.")
            self.service = False
            return

        self.client = MQTTClient(**client_params)  # Initialize the MQTT client
        self.base_topic = f"/{client_params['client_id'].replace('-', '/')}/"
        print(self.base_topic)
        self.topics = topics
        self.command_handler = command_handler
        self.mqtt_publish_queue = asyncQueue()
        self.setup_client()
        self.connected = True
        print(f"Service initialized at {self.base_topic}")

    def setup_client(self):
        self.client.set_callback(self.on_message)
        self.client.set_last_will(self.topics['status'], 'Disconnected', retain=True)

    async def worker(self):
        if not self.service:
            return
        self.client.connect()
        for topic in self.topics['subscriptions']:
            self.client.subscribe(self.base_topic + topic)

        self.client.subscribe("$SYS/broker/uptime")  # Service subscription to keep connection alive

        self.add_message_to_publish(self.topics['status'], "Connected", retain=True)

        tasks = [
            asyncio.create_task(self.handle_incoming_messages()),
            asyncio.create_task(self.publish())
        ]
        await asyncio.sleep(15)  # Await first service message
        while True:
            issue = self.client.is_conn_issue()
            if issue:
                log = self.client.log()
                print(f"log: {log}, issue: {issue}")

                print(f"MQTT Connection issue detected, MQTT attempting to reconnect...")
                if self.client.reconnect():
                    if self.client.is_conn_issue() is None:
                        print("MQTT Failed to reconnect")
                        self.client.log()
                    else:
                        self.client.resubscribe()
                        self.connected = True
                else:
                    self.connected = False
                await asyncio.sleep(15)

    async def handle_incoming_messages(self):
        while self.connected:
            self.client.check_msg()
            await asyncio.sleep(1)

    async def publish(self):
        while self.connected:
            message = await self.mqtt_publish_queue.get()
            if message:
                self.client.publish(message['topic'], message['payload'], retain=message['retain'])
                print(f'Published to {message["topic"]}: {message["payload"]}')
                self.mqtt_publish_queue.task_done()

    def add_message_to_publish(self, topic, data, retain=False):
        if self.service:
            message = {'topic': self.base_topic + topic, 'payload': json.dumps(data), 'retain': retain}
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
        print(f'Received message on topic: {topic.decode()} with message: {msg.decode()}')
        if topic.decode().split("/")[-1] in self.topics['subscriptions']:
            message = self.decode_body(msg)
            if message:
                self.process_command(topic.decode(), message)

    def process_command(self, topic, command):
        # Example command processing based on the topic
        if topic == self.topics['dose']:
            self.command_handler.dose(command)
        elif topic == self.topics['run']:
            self.command_handler.run(command)
        elif topic == self.topics['stop']:
            self.command_handler.stop(command)
        elif topic == self.topics['refill']:
            self.command_handler.refill(command)


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
    topics = {
        'status': 'status',
        'subscriptions': ['dose', 'run', 'stop', 'refill'],
        'dose': 'dose',
        'run': 'run',
        'stop': 'stop',
        'refill': 'refill'
    }
    from asyncscheduler import CommandBuffer
    command_buffer = CommandBuffer
    command_handler = CommandHandler(command_buffer)
    mqtt_worker = MQTTWorker(client_params, topics, command_handler)
    asyncio.create_task(mqtt_worker.worker())
    await asyncio.sleep(1)
    for i in range(10):
        mqtt_worker.add_message_to_publish("test", f"Msg No{i}")
    await asyncio.sleep(120)


if __name__ == '__main__':
    asyncio.run(main())