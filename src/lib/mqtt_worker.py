import json
import time
from lib.mqtt_asyncio import MQTTClient
from lib.decorator import restart_on_failure
try:
    import gc
    from lib.async_queue import Queue as asyncQueue
    import ubinascii
    from machine import unique_id
    from release_tag import *
    from utime import ticks_ms
except ImportError:
    from lib.mocks import unique_id, net
    from asyncio import Queue as asyncQueue
    import binascii as ubinascii

    def ticks_ms():
        return round(time.time() * 1000)

    RELEASE_TAG = "debug version"

import asyncio
import shared


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
        self.stats = stats
        self.command_handler = command_handler
        self.net = network

        self.mqtt_publish_queue = asyncQueue(maxsize=100)
        self.mqtt_client_tasks = []

    async def start(self):
        await self.setup_client()
        print(f"Service initialized at {self.base_topic}")

    async def stop(self):
        print(f"Stop MQTT worker")
        self.service = False
        await self.client.disconnect()
        for task in self.mqtt_client_tasks:
            task.cancel()

    async def setup_client(self):
        if not self.service:
            return
        while not shared.time_synced:
            await asyncio.sleep(1)
        self.client.set_last_will(self.base_topic + 'status', 'Disconnected', retain=True)

        await self.client.subscribe(self.base_topic + 'dose', qos=0, cb=self.command_handler.dose)
        await self.client.subscribe(self.base_topic + 'run', qos=0, cb=self.command_handler.run)
        await self.client.subscribe(self.base_topic + 'stop', qos=0, cb=self.command_handler.stop)
        await self.client.subscribe(self.base_topic + 'refill', qos=0, cb=self.command_handler.refill)

        await self.publish_stats()
        self.mqtt_client_tasks = [asyncio.create_task(self.client.maintain_connection()),
                                  asyncio.create_task(self.client.handle_messages()),
                                  asyncio.create_task(self.publish())
                                  ]

    @restart_on_failure
    async def publish(self):
        while self.service:
            while not self.client.connected or self.client.reconnection_required:
                await asyncio.sleep(1)
            message = await self.mqtt_publish_queue.get()
            if message:
                await self.client.publish(message['topic'], message['payload'].encode('utf-8'), retain=message['retain'])
                print(f'Published to {message["topic"]}: {message["payload"]}')
                self.mqtt_publish_queue.task_done()
        print("Stop MQTT publish task")
        await asyncio.sleep(10)

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
                print(f"MQTT Connected: {self.client.connected}, Reconnect need: {self.client.reconnection_required}")

            message = {'topic': self.base_topic + topic, 'payload': data, 'retain': retain}
            print(f"MQTT add message {message}")
            await self.mqtt_publish_queue.put(message)

    @staticmethod
    def decode_body(msg):
        try:
            print("MQTT decode message: ", msg.decode('ascii'))
            mqtt_body = json.loads(msg.decode('ascii'))
            print(mqtt_body)
            return mqtt_body
        except Exception as mqtt_decode_e:
            print(f"Failed to decode mqtt message: {msg}, ", mqtt_decode_e)
        return False

    def process_command(self, topic, command):
        if topic == "uptime":
            print("MQTT update keepalive timer")
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
    shared.time_synced = True
    asyncio.create_task(shared.mqtt_worker.start())
    await asyncio.sleep(1)
    for i in range(100):
        await shared.mqtt_worker.add_message_to_publish(f"test", f"Msg No{i}")
        await asyncio.sleep(2)
    await asyncio.sleep(120)


if __name__ == '__main__':
    asyncio.run(main())
