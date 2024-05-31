import requests
from lib.decorator import restart_on_failure
try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

# Seconds between notifications send attend
DELAY = 60*10

# Retries if network error
RETRIES = 3
RETRY_DELAY = 20


def quote_plus(s):
    return s.replace('%', '%25').replace('+', '%2B').replace(' ', '+').replace('&', '%26').replace('?', '%3F') + '%0A'


class MessagingService:
    def __init__(self, service_name):
        self.service_name = service_name

    async def send_request(self, url):
        max_retries = RETRIES
        retry_delay = RETRY_DELAY
        for attempt in range(max_retries):
            try:
                print(f"Send message from {self.service_name}: ", url)
                response = requests.get(url, timeout=5)

                if response.status_code == 503:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                    continue

                elif self.service_name == "WhatsApp" and response.status_code in [404, 203, 414]:
                    print(f"{self.service_name} Notification rejected")

                elif self.service_name == "WhatsApp" and response.status_code != 200:
                    print(f"{self.service_name} HTTP Error: {response.status_code}")
                    print(response.text)

                # CallmeBot returns code 200 for all Telegram API messages, even with fake account
                elif self.service_name == "Telegram" and response.status_code == 200 and "Error Code" in response.text:
                    print(f"{self.service_name} Notification rejected: \n {response.text}")

                elif response.status_code == 200:
                    print(f"{self.service_name} send message success \n{response.text}")
                else:
                    print(f"{self.service_name} unknown message status, response code: {response.status_code}")
                    print(response.text)

                return

            except Exception as e:
                print(f"{self.service_name} Network error: ", e)
                await asyncio.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
        return


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

    def prepare_message_url(self, message):
        return f'https://api.callmebot.com/whatsapp.php?phone={self.phone}&apikey={self.apikey}&text={message}'


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

    def prepare_message_url(self, message):
        return f'https://api.callmebot.com/text.php?user={self.username}&text={message}'


class NotificationWorker:
    def __init__(self, service, net):
        self.service = service
        self.net = net
        self.buffer = []
        self.lock = asyncio.Lock()
        self.active = True if service.active else False
        self.message = ""

    async def add_message(self, message):
        if not self.active:
            return
        async with self.lock:
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
            print(f"{self.service.service_name} Start")
            print(f"{self.service.service_name} await {DELAY}sec")
            print("Wifi status: ", self.net.isconnected())
            print(self.buffer)
            await asyncio.sleep(DELAY)
            print(self.buffer)
            if self.buffer and self.net.isconnected():
                await self.buffer_to_message()
                url = self.service.prepare_message_url(self.message)
                await self.service.send_request(url)
            print(f"{self.service.service_name} Finish")


# Example of notifications usage
async def debug_notification():
    import time
    global DELAY
    DELAY = 5
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

    whatsapp_worker = NotificationWorker(whatsapp, wifi)
    telegram_worker = NotificationWorker(telegram, wifi)

    asyncio.create_task(whatsapp_worker.process_messages())
    asyncio.create_task(telegram_worker.process_messages())

    for i in range(51):
        await whatsapp_worker.add_message(f"WhatsApp&No{i}? 100% Run+Test")
        await telegram_worker.add_message(f"Telegram&No{i}? 100% Run+Test")

    await asyncio.sleep(15)


if __name__ == "__main__":
    asyncio.run(debug_notification())
