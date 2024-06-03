import json

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
        self.client = MQTTClient(**client_params)  # Initialize the MQTT client
        self.base_topic = f"/{client_params['client_id'].replace('-', '/')}/"
        print(self.base_topic)
        self.topics = topics
        self.command_handler = command_handler
        self.mqtt_publish_queue = asyncQueue()
        self.setup_client()

    def setup_client(self):
        self.client.set_callback(self.on_message)
        self.client.set_last_will(self.topics['status'], 'Disconnected', retain=True)

    async def worker(self):
        try:
            self.client.connect()
            for topic in self.topics['subscriptions']:
                self.client.subscribe(self.base_topic + topic)
            await asyncio.gather(
                self.handle_incoming_messages(),
                self.publish()
            )
        except Exception as e:
            print(f'MQTT connection error: {e}')

    async def handle_incoming_messages(self):
        while True:
            self.client.check_msg()
            await asyncio.sleep(0.1)  # Ensure this doesn't hog the CPU

    async def publish(self):
        while True:
            message = await self.mqtt_publish_queue.get()
            self.client.publish(message['topic'], message['payload'])
            print(f'Published to {message["topic"]}: {message["payload"]}')
            self.mqtt_publish_queue.task_done()

    def add_message_to_publish(self, topic, data):
        message = {'topic': self.base_topic + topic, 'payload': json.dumps(data)}
        print(f"MQTT add message {message}")
        asyncio.create_task(self.mqtt_publish_queue.put(message))

    def on_message(self, topic, msg, retain, dup):
        print(f'Received message on topic: {topic.decode()} with message: {msg.decode()}')
        try:
            message = json.loads(msg.decode())
            if topic.decode() in self.topics['subscriptions']:
                self.process_command(topic.decode(), message)
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON: {e}")

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


class CommandHandler:
    def dose(self, command):
        print(f"Handling dosing command: {command}")

    def run(self, command):
        print(f"Handling run command: {command}")

    def stop(self, command):
        print(f"Handling stop command: {command}")

    def refill(self, command):
        print(f"Handling refill command: {command}")


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

    client_params = {'client_id': "ReefRhythm-" + unique_id, 'server': broker, 'port': 1883, 'user': user, 'password': password}
    topics = {
        'status': 'status',
        'subscriptions': ['dose', 'run', 'stop', 'refill'],
        'dose': 'dose',
        'run': 'run',
        'stop': 'stop',
        'refill': 'refill'
    }
    command_handler = CommandHandler()
    mqtt_worker = MQTTWorker(client_params, topics, command_handler)
    asyncio.create_task(mqtt_worker.worker())
    await asyncio.sleep(1)
    for i in range(10):
        mqtt_worker.add_message_to_publish("test", f"Msg No{i}")
    await asyncio.sleep(15)

if __name__ == '__main__':
    asyncio.run(main())