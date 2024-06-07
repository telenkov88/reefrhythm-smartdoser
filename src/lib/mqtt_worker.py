import json
import time

try:
    import gc
    from lib.umqtt.robust2 import MQTTClient
    from lib.async_queue import Queue as asyncQueue
    import ubinascii
    from machine import unique_id
    from release_tag import *
    from utime import ticks_ms


except ImportError:
    from lib.mocks import MQTTClient, unique_id, net
    from asyncio import Queue as asyncQueue
    import binascii as ubinascii

    def ticks_ms():
        return round(time.time() * 1000)

    RELEASE_TAG = "debug version"

import asyncio
import shared

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

        self.mqtt_publish_queue = asyncQueue(maxsize=100)
        self.setup_client()
        self.connected = False
        self.keepalive = shared.mqtt_keepalive + 1
        self.last_message = 0
        print(f"Service initialized at {self.base_topic}")

    def setup_client(self):
        self.client.set_callback(self.on_message)
        self.client.set_last_will(self.base_topic + self.topics['status'], 'Disconnected', retain=True)

    async def ensure_connected(self):
        while not self.net.isconnected():
            print("Waiting for network connection...")
            await asyncio.sleep(1)

        try:
            self.client.reconnect()
            await asyncio.sleep(6)  # Wait if socket not ready error
            if self.client.conn_issue:
                raise ValueError("Fail to reconnect")
            self.client.resubscribe()

            print(f"MQTT Await connection for up to {self.keepalive} seconds...")
            timeout = self.keepalive
            _last_messages = self.last_message
            while timeout > 0:
                self.client.ping()
                if self.last_message != _last_messages:
                    print("MQTT got connection")
                    self.connected = True
                    await self.add_message_to_publish(self.topics['status'], "Connected", retain=True)
                    await self.publish_stats()
                    return True
                print("MQTT wait for connection")
                await asyncio.sleep(5)
                timeout -= 5

            print("MQTT reconnect failed after timeout")
            self.connected = False
        except Exception as e:
            print("MQTT Reconnection Error: ", e)
            self.connected = False
        finally:
            if not self.connected:
                try:
                    self.client.disconnect()  # Ensure this is non-blocking or handled asynchronously
                except Exception as e:
                    print("MQTT Disconnect Error: ", e)
                await asyncio.sleep(self.client.keepalive)
            return False

    async def ping_server(self):
        if not self.service:
            return
        while True:
            if self.connected and self.service:
                self.client.ping()
            await asyncio.sleep(10)

    async def worker(self):
        if not self.service:
            return
        while not shared.time_synced:
            await asyncio.sleep(1)
        try:
            self.client.connect()
            await asyncio.sleep(5)
            if self.client.conn_issue():
                raise
            await self.add_message_to_publish(self.topics['status'], "Connected", retain=True)
        except Exception:
            print("MQTT Error during initial connect")
            self.connected = False
            try:
                self.client.disconnect()
            except Exception as e:
                print("MQTT Disconnect Error: ", e)

        for topic in self.topics['subscriptions']:
            self.client.subscribe(self.base_topic + topic)
        self.client.subscribe("$SYS/broker/uptime")  # Service subscription for keepalive
        await self.publish_stats()

        tasks = [
            asyncio.create_task(self.handle_incoming_messages()),
            asyncio.create_task(self.publish()),
            asyncio.create_task(self.ping_server())
        ]

        while True:
            while not self.service:
                await asyncio.sleep(1)
            if self.client.is_conn_issue() or not self.connected or \
                    time.time() > self.last_message + (self.keepalive + 1):
                self.connected = False
                print("MQTT Connection issue detected, attempting to reconnect...")
                if time.time() > self.last_message + (self.keepalive + 1):
                    print("MQTT timeout for service message: ", self.last_message, " , time: ", time.time())
                else:
                    print("MQTT Issue: ", self.client.is_conn_issue(), " Connected: ", self.connected)
                await self.ensure_connected()
            else:
                print("MQTT Connected")
                await asyncio.sleep(10)

    async def handle_incoming_messages(self):
        while self.service:
            try:
                self.client.check_msg()
            except Exception as e:
                print("MQTT error: ", e)
            await asyncio.sleep(1)

    async def publish(self):
        while self.service:
            while not self.connected:
                await asyncio.sleep(1)
            message = await self.mqtt_publish_queue.get()
            if message:
                self.client.publish(message['topic'], message['payload'], retain=message['retain'])
                print(f'Published to {message["topic"]}: {message["payload"]}')
                self.mqtt_publish_queue.task_done()

    async def publish_stats(self, new_stats=None):
        if self.service:
            if new_stats is not None:
                print("MQTT Update stats: ", new_stats)
                self.stats = new_stats
            await self.add_message_to_publish("ip", "" + self.net.ifconfig()[0], retain=True)
            for _topic in self.stats:
                if "pump" in _topic:
                    await self.add_message_to_publish(_topic, self.stats[_topic], retain=False)
                else:
                    await self.add_message_to_publish(_topic, self.stats[_topic], retain=True)

    async def add_message_to_publish(self, topic, data, retain=False):
        if self.service:
            if self.mqtt_publish_queue.full():
                # Remove the oldest message to make space for the new one
                discarded_message = await self.mqtt_publish_queue.get()
                print(f"Discarding oldest message due to queue overflow: {discarded_message}")

            message = {'topic': self.base_topic + topic, 'payload': data, 'retain': retain}
            print(f"MQTT add message {message}")
            await self.mqtt_publish_queue.put(message)

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
        print(f'Received message on topic: {_topic}')
        if _topic.split("/")[-1] in self.topics['subscriptions'] or _topic == "$SYS/broker/uptime":
            if _topic == "$SYS/broker/uptime":
                message = msg.decode()
            else:
                message = self.decode_body(msg)
            if message:
                self.process_command(_topic.split("/")[-1], msg)

    def process_command(self, topic, command):
        if topic == "uptime":
            print("MQTT update keepalive timer")
            self.client.conn_issue = None
            self.last_message = time.time()
            self.connected = True
            return
        print(f"MQTT process command, {topic}, {command}")
        try:
            cmd = json.loads(command.decode())
        except Exception as e:
            print("MQTT process command error ", e)
            return

        if topic == 'dose':
            asyncio.create_task(self.command_handler.dose(cmd))
        elif topic == 'run':
            asyncio.create_task(self.command_handler.run(cmd))
        elif topic == 'stop':
            asyncio.create_task(self.command_handler.stop(cmd))
        elif topic == 'refill':
            asyncio.create_task(self.command_handler.refill(cmd))
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

    client_params = {'client_id': "ReefRhythm-" + shared.mqtt_id,
                     'server': broker, 'port': 1883, 'user': user, 'password': password}

    stats = {"version": "debug_version", "hostname": "localhost"}
    from lib.pump_control import CommandHandler
    command_handler = CommandHandler()
    mqtt_worker = MQTTWorker(client_params, stats, command_handler, shared.wifi)
    asyncio.create_task(mqtt_worker.worker())
    await asyncio.sleep(1)
    for i in range(100):
        await mqtt_worker.add_message_to_publish(f"test", f"Msg No{i}")
        await asyncio.sleep(10)
    await asyncio.sleep(120)


if __name__ == '__main__':
    asyncio.run(main())
