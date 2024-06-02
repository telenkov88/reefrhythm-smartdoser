from lib.decorator import restart_on_failure
try:
    import uasyncio as asyncio
    import usocket
except ImportError:
    import asyncio
    import socket as usocket

import ssl

# Retries if network error
RETRIES = 3
RETRY_DELAY = 20


def quote_plus(s):
    return s.replace('%', '%25').replace('+', '%2B').replace(' ', '+').replace('&', '%26').replace('?', '%3F') + '%0A'


# Initialize SSL context once per application or service
ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
if hasattr(ssl_context, "check_hostname"):
    ssl_context.check_hostname = False  # Disable hostname checking
ssl_context.verify_mode = ssl.CERT_NONE  # Disable certificate verification


class MessagingService:
    def __init__(self, service_name):
        self.service_name = service_name
        self.ssl_context = ssl_context  # Use the same SSL context for each service instance

    async def send_request(self, host, path):
        max_retries = RETRIES
        retry_delay = RETRY_DELAY
        request_header = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
        reader, writer = None, None

        for attempt in range(max_retries):
            try:
                print(host)
                reader, writer = await asyncio.open_connection(host, 443, ssl=self.ssl_context, server_hostname=host)
                writer.write(request_header.encode())
                await writer.drain()

                response = await reader.read()
                response = response.decode()
                status_code = int(response.split(' ')[1])
                response_text = response.split('\r\n\r\n', 1)[1]

                writer.close()
                await writer.wait_closed()
                if self.process_response(status_code, response_text):
                    return  # Exit on success
            except Exception as e:
                print(f"{self.service_name} Network error on attempt {attempt + 1}: {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
            finally:
                if writer:
                    writer.close()
                    await writer.wait_closed()
                print("Finish")

    def process_response(self, status_code, response_text):
        # Handle different status codes and log or act accordingly
        print("Status code", status_code)
        print("Response:", response_text)

        if status_code == 503:
            return False
        elif self.service_name == "WhatsApp" and status_code in [404, 203, 414]:
            print(f"{self.service_name} Notification rejected")

        elif self.service_name == "WhatsApp" and status_code != 200:
            print(f"{self.service_name} HTTP Error: {status_code}")

        # CallmeBot returns code 200 for all Telegram API messages, even with fake account
        elif self.service_name == "Telegram" and status_code == 200 and "Error Code" in response_text:
            print(f"{self.service_name} Notification rejected: \n {response_text}")

        elif status_code == 200:
            print(f"{self.service_name} send message success \n{response_text}")
        else:
            print(f"{self.service_name} unknown message status, response code: {status_code}")
            print(response_text)

        return True


class Whatsapp(MessagingService):
    def __init__(self, phone, apikey):
        super().__init__("WhatsApp")
        if not phone or not apikey:
            self.active = False
            print("Stop WhatsApp worker due to missing phone or apikey")
        else:
            self.active = True
            print(f"WhatsApp phone: ", phone)

        self.phone = phone
        self.apikey = apikey
        self.buffer_size = 10
        self.host = 'api.callmebot.com'

    def path(self, message):
        return f'/whatsapp.php?phone={self.phone}&apikey={self.apikey}&text={message}'


class Telegram(MessagingService):
    def __init__(self, username):
        super().__init__("Telegram")
        if not username:
            self.active = False
            print("Stop Telegram worker due to missing username")
        else:
            self.active = True
            print("Telegram username ", username)

        self.username = username
        self.buffer_size = 50
        self.host = 'api.callmebot.com'

    def path(self, message):
        return f'/text.php?user={self.username}&text={message}'


class NotificationWorker:
    def __init__(self, service, net, delay=600, background=True):
        self.service = service
        self.net = net
        self.buffer = []
        self.active = True if service.active else False
        self.message = ""
        self.background = background
        self.lock = asyncio.Lock()
        self.delay = delay

    async def add_message(self, message):
        if not self.active:
            return
        async with self.lock:  # Now this should work as expected
            self.buffer.append(message)
            print(f"{self.service.service_name} add message: {message}")
            while len(self.buffer) > self.service.buffer_size:
                self.buffer.pop(0)

    async def buffer_to_message(self):
        self.message = ""
        async with self.lock:
            for msg in self.buffer:
                self.message += quote_plus(msg)
            self.buffer = []

    @restart_on_failure
    async def process_messages(self):
        while self.active:
            print(f"[{self.service.service_name}] Start")
            if self.background:
                print(f"[{self.service.service_name}] await {self.delay}sec")
                await asyncio.sleep(self.delay)
            print(f"[{self.service.service_name}] Wifi status: ", self.net.isconnected())
            print(f"[{self.service.service_name}] buffer:", self.buffer)
            if self.buffer and self.net.isconnected():
                await self.buffer_to_message()
                await self.service.send_request(self.service.host, self.service.path(self.message))
            print(f"[{self.service.service_name}] Finish")
            if not self.background:
                break


# Example of notifications usage
async def debug_notification():
    import time
    try:
        # Debug on PC
        from unittest.mock import MagicMock
        wifi = MagicMock()
        wifi.isconnected = MagicMock(return_value=True)

    except ImportError:
        import json
        import network

        # {"ssid": "ssid name", "password": "your wifi password"}
        with open("./config/wifi.json", 'r') as wifi_config:
            wifi_settings = json.load(wifi_config)
            wifi = network.WLAN(network.STA_IF)
            wifi.active(True)
            print("connect to wifi")
            wifi.connect(wifi_settings["ssid"], wifi_settings["password"])

        while not wifi.isconnected():
            print("Wait for wifi")
            time.sleep(3)
    try:
        import json
        # {"telegram": "nickname", "whatsapp_number": "phone number", "whatsapp_apikey": "callmebot apikey number"}
        with open("./config/settings.json", 'r') as read_file:
            settings = json.load(read_file)
            whatsapp_number = settings["whatsapp_number"]
            whatsapp_apikey = settings["whatsapp_apikey"]
            print(f"Using whatsapp phone: {whatsapp_number}")

            telegram_nickname = settings["telegram"]
            print(f"Using telegram nickname: {telegram_nickname}")
    except OSError:
        print("Using fake CallMeBot accounts")
        whatsapp_number = "whatsapp_phone"
        whatsapp_apikey = "whatsapp_apikey"
        telegram_nickname = "telegram_nickname"

    whatsapp = Whatsapp(whatsapp_number, whatsapp_apikey)
    telegram = Telegram(telegram_nickname)

    whatsapp_worker = NotificationWorker(whatsapp, wifi, delay=5)
    telegram_worker = NotificationWorker(telegram, wifi, delay=5)

    asyncio.create_task(whatsapp_worker.process_messages())
    asyncio.create_task(telegram_worker.process_messages())

    for i in range(51):
        await whatsapp_worker.add_message(f"WhatsApp&No{i}? 100% Run+Test")
        await telegram_worker.add_message(f"Telegram&No{i}? 100% Run+Test")

    await asyncio.sleep(15)


if __name__ == "__main__":
    asyncio.run(debug_notification())
