"""
connect: Establishes an asynchronous connection to the MQTT server, handling both non-SSL and SSL connections.
_send_connect and _receive_connack: Handle the MQTT connection handshake.
publish: Sends messages to a topic, with support for QoS 1 acknowledgment handling.
subscribe: Subscribes to a topic and handles acknowledgment of the subscription.
"""
import json
import time
import asyncio
from lib.decorator import restart_on_failure
try:
    import ubinascii as binascii
except ImportError:
    import binascii


class MQTTException(Exception):
    pass


def pid_gen(pid=0):
    while True:
        pid = pid + 1 if pid < 65535 else 1
        yield pid


class MQTTClient:
    def __init__(self, client_id, server, port=0, user=None, password=None, keepalive=60,
                 ssl=False, ssl_params=None, debug=False, socket_timeout=5):
        self.DEBUG = debug
        self.last_will_topic = None
        self.last_will_message = None
        self.last_will_qos = 0
        self.last_will_retain = False

        self.client_id = client_id.encode('ascii')  # First, convert to bytes
        self.server = server
        self.port = port if port else (8883 if ssl else 1883)
        self.user = user
        self.password = password
        self.keepalive = keepalive
        self.last_ping_time = 0  # Timestamp of the last PINGREQ
        self.reconnect_timeout = 10
        self.socket_timeout = socket_timeout

        self.ssl = ssl
        self.ssl_params = ssl_params if ssl_params else {}
        self.reader = None
        self.writer = None
        self.connected = False
        self.reconnection_required = False
        self.subscribed = False
        self.newpid = pid_gen()
        self.subscriptions = {}  # Dictionary to keep track of topic subscriptions

    def set_last_will(self, topic, msg, qos=0, retain=False):
        self.last_will_topic = topic
        self.last_will_message = msg
        self.last_will_qos = qos
        self.last_will_retain = retain

    async def reset_connection(self):
        self.writer.close()
        await self.writer.wait_closed()
        print("Connection reset initiated.")
        self.reconnection_required = True
        self.subscribed = False

    async def safe_write(self, data):
        # TODO socker leaks for reconnect here:
        if not self.writer:
            raise MQTTException("No connection available for writing.")
        try:
            self.writer.write(data)
            await asyncio.wait_for(self.writer.drain(), timeout=self.socket_timeout)
        except asyncio.TimeoutError as e:
            print(f"Error: Write timeout occurred: {e}")
            self.reconnection_required = True
            await self.disconnect()
        except Exception as e:
            print(f"Error: Failed to write data: {e}")
            self.reconnection_required = True
            raise

    async def connect(self, clean_session=True):
        print("Try to connect ", self.server)
        mqtt = asyncio.open_connection(self.server, self.port)
        try:
            self.reader, self.writer = await asyncio.wait_for(mqtt, timeout=self.socket_timeout)
        except Exception as e:
            print("Connection failed, ", e)
            self.connected = False
            return False
        await self._send_connect(clean_session)
        await self._receive_connack()
        if clean_session:
            self.subscriptions = {}  # Clear previous subscriptions if clean session
        elif not self.subscribed:
            await self.resubscribe_all()  # Resubscribe to all topics if not a clean session
        if self.last_will_topic:
            await self.publish(self.last_will_topic, b"Connected", retain=self.last_will_retain)

    async def resubscribe_all(self):
        """Resubscribes to all topics after a reconnection."""
        if not self.connected:
            print("Cannot resubscribe: Client is not connected.")
            return
        for topic, (qos, cb) in self.subscriptions.items():
            print(f"Resubscribing to {topic} with QoS {qos}")
            await self.subscribe(topic, qos, cb)
        self.subscribed = True

    async def _send_connect(self, clean_session):
        packet = bytearray(b"\x10")  # Connect command
        # Start with a base length which includes:
        # protocol name, version, connect flags, keepalive, and client ID length
        remaining_length = 2 + 4 + 1 + 1 + 2 + 2 + len(self.client_id)

        connect_flags = 0x02 if clean_session else 0
        if self.last_will_topic:
            connect_flags |= 0x04 | (self.last_will_qos << 3)
            if self.last_will_retain:
                connect_flags |= 0x20
            remaining_length += 2 + len(self.last_will_topic) + 2 + len(
                self.last_will_message)  # Add lengths of the last will topic and message

        if self.user:
            connect_flags |= 0x80
            remaining_length += 2 + len(self.user.encode('utf-8'))  # Add length of the username
            if self.password:
                connect_flags |= 0x40
                remaining_length += 2 + len(self.password.encode('utf-8'))  # Add length of the password

        # Build the CONNECT packet with the last will
        packet += self._encode_length(remaining_length)
        packet += b"\x00\x04MQTT\x04" + bytes([connect_flags]) + self.keepalive.to_bytes(2, 'big')

        packet += len(self.client_id).to_bytes(2, 'big') + self.client_id
        if self.last_will_topic:
            packet += len(self.last_will_topic).to_bytes(2, 'big') + self.last_will_topic.encode('utf-8')
            packet += len(self.last_will_message).to_bytes(2, 'big') + self.last_will_message.encode('utf-8')
        if self.user:
            packet += len(self.user).to_bytes(2, 'big') + self.user.encode('utf-8')
            if self.password:
                packet += len(self.password).to_bytes(2, 'big') + self.password.encode('utf-8')

        await self.safe_write(packet)

    async def _receive_connack(self):
        resp = await self.reader.readexactly(4)
        if not (resp[0] == 0x20 and resp[1] == 0x02):
            raise MQTTException("Invalid CONNACK")
        if resp[3] != 0:
            raise MQTTException(f"CONNACK returned error code {resp[3]}")
        self.connected = True

    @staticmethod
    def _encode_length(length):
        encoded = bytearray()
        while True:
            encoded_byte = length % 128
            length //= 128
            # if there are more data to encode, set the top bit of this byte
            if length > 0:
                encoded_byte |= 128
            encoded.append(encoded_byte)
            if length == 0:
                break
        return encoded

    async def _recv_len(self):
        multiplier = 1
        value = 0
        while True:
            encoded_byte = await self.reader.readexactly(1)
            encoded_byte = encoded_byte[0]
            value += (encoded_byte & 127) * multiplier
            if encoded_byte & 128 == 0:
                break
            multiplier *= 128
            if multiplier > 2097152:  # 128 * 128 * 128
                raise MQTTException("Malformed Remaining Length")
        return value

    async def publish(self, topic, msg, retain=False, qos=0, dup=False):
        try:
            packet = bytearray(b"\x30")
            packet[0] |= qos << 1 | retain | dup << 3
            remaining_length = 2 + len(topic) + len(msg)
            if qos > 0:
                remaining_length += 2  # Packet Identifier
            packet += self._encode_length(remaining_length)
            packet += len(topic).to_bytes(2, 'big') + topic.encode("utf-8")
            pid = None
            if qos > 0:
                pid = next(self.newpid)
                packet += pid.to_bytes(2, 'big')
            packet += msg
            await self.safe_write(packet)
            if qos == 1:
                await self._wait_for_puback(pid)
        except Exception as e:
            print("MQTT publish exception ", e)
            self.reconnection_required = True

    async def _wait_for_puback(self, pid):
        while True:
            try:
                header = await self.reader.readexactly(1)
                if header[0] >> 4 != 4:  # PUBACK
                    continue
                size = await self._recv_len()
                if size != 2:
                    continue
                received_pid = int.from_bytes(await self.reader.readexactly(2), 'big')
                if received_pid == pid:
                    break
            except Exception as e:
                print("Error in _wait_for_puback ", e)
                self.reconnection_required = True

    def _prepare_subscribe_packet(self, topic, qos, pid):
        """Prepare the SUBSCRIBE packet."""
        packet = bytearray(b"\x82")  # SUBSCRIBE fixed header
        remaining_length = 2 + 2 + len(topic) + 1  # Remaining length calculation
        packet += self._encode_length(remaining_length)
        packet += pid.to_bytes(2, 'big')
        packet += len(topic).to_bytes(2, 'big') + topic.encode('utf-8')
        packet += bytes([qos])
        return packet

    async def subscribe(self, topic, qos=0, cb=None):
        """Subscribes to a topic and registers a callback."""
        print(f"Subscribe to '{topic}'")
        # Assign the callback if provided and valid
        if cb and callable(cb):
            self.subscriptions[topic] = (qos, cb)
        elif cb is None:
            self.subscriptions[topic] = (qos, self.on_message)  # Default callback method
        else:
            raise ValueError("Callback is not callable.")

        if not self.connected:
            print("Client is not connected.")
            self.subscribed = False
            return
        pid = next(self.newpid)
        packet = self._prepare_subscribe_packet(topic, qos, pid)
        await self.safe_write(packet)
        await self._wait_for_suback(pid)

    def _prepare_unsubscribe_packet(self, topic):
        """Prepare the UNSUBSCRIBE packet."""
        packet = bytearray(b"\xA2")  # UNSUBSCRIBE fixed header
        pid = next(self.newpid)
        remaining_length = 2 + 2 + len(topic)
        packet += self._encode_length(remaining_length)
        packet += pid.to_bytes(2, 'big')
        packet += len(topic).to_bytes(2, 'big') + topic.encode('utf-8')
        return packet

    async def unsubscribe(self, topic):
        """Unsubscribes from a topic."""
        if topic in self.subscriptions:
            packet = self._prepare_unsubscribe_packet(topic)
            await self.safe_write(packet)
            await self._wait_for_unsuback(next(self.newpid))
            del self.subscriptions[topic]  # Remove from subscriptions
        else:
            print(f"No subscription found for topic {topic}")

    async def _wait_for_unsuback(self, pid):
        """Waits for an UNSUBACK packet that acknowledges the unsubscription."""
        while True:
            header = await self.reader.readexactly(1)
            if header[0] >> 4 != 11:  # UNSUBACK packet type
                continue
            await self._recv_len()
            received_pid = int.from_bytes(await self.reader.readexactly(2), 'big')
            if received_pid == pid:
                break
        print("Unsubscription acknowledged.")

    async def _wait_for_suback(self, pid):
        """
        Waits for a SUBACK packet that acknowledges the subscription.

        :param pid: The packet identifier of the SUBSCRIBE packet.
        """
        while True:
            header = await self.reader.readexactly(1)
            if header[0] >> 4 != 9:  # SUBACK packet type
                continue
            await self._recv_len()
            received_pid = int.from_bytes(await self.reader.readexactly(2), 'big')
            if received_pid != pid:
                continue
            # handle the SUBACK payload, e.g., status
            status = await self.reader.readexactly(1)
            if status[0] == 0x80:
                raise MQTTException("Subscription failed.")
            break

    async def disconnect(self):
        """Attempts to gracefully close the MQTT connection and falls back to forcing the socket closed."""
        self.subscribed = False
        if self.writer:
            try:
                # Attempt to send the DISCONNECT packet
                self.writer.write(bytearray([0xE0, 0x00]))  # MQTT DISCONNECT packet
                await asyncio.wait_for(self.writer.drain(), timeout=self.socket_timeout)
            except Exception as e:
                print(f"Error during graceful disconnect: {e}")
            finally:
                # Force close the writer to ensure the connection is terminated
                try:
                    self.writer.close()
                    await self.writer.wait_closed()
                except Exception as e:
                    print(f"Failed to close connection: {e}")
        self.connected = False
        print("Disconnected.")

    async def reconnect(self):
        backoff_time = 2
        max_backoff_time = 300  # Maximum backoff should be reasonably limited
        while not self.connected and backoff_time <= max_backoff_time:
            print(f"Reconnecting in {backoff_time} seconds...")
            await asyncio.sleep(backoff_time)
            backoff_time *= 2
            await self.disconnect()  # Ensure it's fully disconnected
            try:
                await self.connect(clean_session=False)
            except Exception as e:
                print(f"Reconnect failed: {e}")
                await asyncio.sleep(10)
                backoff_time += 10
            else:
                if self.connected:
                    print("Reconnected successfully.")
                    break
        if not self.connected:
            print("Failed to reconnect after several attempts.")

    async def ping(self):
        if not self.connected and not self.reconnection_required:
            print("Not connected, skipping ping.")
            print("Not connected, skipping ping.")
            return
        try:
            await self.safe_write(b'\xc0\x00')  # Sending PINGREQ
        except Exception as e:
            print(f"Failed to send ping: {e}")
            self.reconnection_required = True

    @restart_on_failure
    async def maintain_connection(self):
        print("MQTT maintain connection worker start")
        while True:

            if not self.connected or self.reconnection_required:
                print("Attempting to reconnect...")
                await self.reconnect()
                self.reconnection_required = False  # Reset flag after attempting to reconnect
            else:
                await self.ping()  # Send periodic pings if connected
            await asyncio.sleep(self.keepalive // 2)  # Check connection health at regular intervals

    @staticmethod
    def on_message(topic, message):
        print(f"Received message on {topic}: {message}")

    async def read_exactly(self, num_bytes):
        try:
            return await asyncio.wait_for(self.reader.readexactly(num_bytes), timeout=self.socket_timeout)
        except asyncio.TimeoutError:
            raise MQTTException("Timeout occurred while trying to read from the broker.")
        except asyncio.IncompleteReadError:
            raise MQTTException("Incomplete read from broker.")

    @restart_on_failure
    async def handle_messages(self):
        while True:
            if self.connected:
                try:
                    # print("Waiting for message...")
                    first_byte = await self.reader.read(1)
                    if not first_byte:
                        print("Connection appears to be closed by the broker.")
                        self.connected = False
                        self.reconnection_required = True
                        continue  # Continue waiting without erroring out

                    message_type = first_byte[0] >> 4
                    flags = first_byte[0]
                    qos = (flags >> 1) & 0x03

                    remaining_length = await self._recv_len()  # Make sure this also gracefully handles waiting
                    if message_type == 3:  # PUBLISH
                        await self._handle_publish(remaining_length, qos)

                except MQTTException as e:
                    print("MQTT Error:", e)
                    break
                except Exception as e:
                    print("Unexpected error:", e)
                    self.connected = False  # Could signal a need to reconnect depending on the error
            await asyncio.sleep(1)

    async def _handle_message(self):
        try:
            first_byte = await self.reader.readexactly(1)
            if not first_byte:  # Check if the read returned an empty bytes object
                raise MQTTException("Connection closed by broker.")
            message_type = first_byte[0] >> 4
            remaining_length = await self._recv_len()

            if message_type == 3:  # PUBLISH
                await self._handle_publish(remaining_length, qos=0)
            elif message_type == 9:  # SUBACK
                await self._handle_suback()
            elif message_type == 13:  # PINGRESP
                self.last_ping_time = time.time()
                await self._handle_pingresp()
            else:
                print(f"Unhandled message type {message_type}")
            # Add other message types as necessary
        except asyncio.IncompleteReadError:
            print("Connection lost")
            self.connected = False

    async def _handle_publish(self, remaining_length, qos):
        """Handle an incoming publish message with QoS parameter."""
        try:
            topic_length_bytes = await self.reader.readexactly(2)
            topic_length = int.from_bytes(topic_length_bytes, 'big')
            topic = await self.reader.readexactly(topic_length)
            topic = topic.decode('utf-8')

            packet_id_bytes = b''
            if qos > 0:
                print("QoS: ", qos)
                packet_id_bytes = await self.reader.readexactly(2)  # Read packet ID for QoS 1 or 2

            message_length = remaining_length - 2 - topic_length
            if qos > 0:
                message_length -= 2  # Adjust for packet ID

            message = await self.reader.readexactly(message_length)

            if qos == 1:
                ack_packet = bytearray([0x40, 0x02]) + packet_id_bytes
                await self.safe_write(ack_packet)

            try:
                message = message.decode('utf-8')
                message = json.loads(message)
            except Exception as e:
                print("Error: failed to decode message, ", e)
                return

            # Callback execution
            if topic in self.subscriptions:
                _, callback = self.subscriptions[topic]
                asyncio.create_task(callback(message))

        except asyncio.IncompleteReadError as e:
            print(f"Error while handling publish: {e}")
            raise MQTTException("Error while handling publish")

    async def _handle_suback(self):
        await self.reader.readexactly(2)  # Read the packet identifier
        return_code = await self.reader.readexactly(1)
        if return_code == b'\x80':
            raise MQTTException("Subscription failed")
        print(f"Subscription acknowledged with QoS {return_code.hex()}")

    @staticmethod
    async def _handle_pingresp():
        print("Ping response received")


def custom_message_handler(topic, message):
    print(f"Received message on topic {topic}: |{message}")


# Usage
async def main():
    client = MQTTClient("clientid", "192.168.254.157", user="mosquitto", password="mosquitto", keepalive=16)
    client.set_last_will("hello/status", "Disconnected")
    await client.subscribe("/test", qos=0, cb=custom_message_handler)
    await client.publish("hello/world", b"Hello MQTT", qos=0)
    await asyncio.sleep(36000)  # Keep running for 10 hour
    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
