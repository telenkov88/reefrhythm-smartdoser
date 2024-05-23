try:
    import urequests as requests
    import uasyncio as asyncio
except ImportError:
    import requests
    import asyncio
import _thread


# Function to make the blocking HTTPS GET request
def blocking_request(url, result):
    try:
        response = requests.get(url)
        result.append(response.text)
    except Exception as e:
        result.append(str(e))


async def async_get_request(url):
    result = []
    # Start a new thread to perform the blocking request
    _thread.start_new_thread(blocking_request, (url, result))

    # Wait until the result is populated
    while not result:
        await asyncio.sleep(1)

    # Return the result
    return result[0]


class Whatsapp:
    def __init__(self, phone, apikey):
        self.PHONE = phone
        self.APIKEY = apikey

    def send_message(self, message):
        url = 'https://api.callmebot.com/whatsapp.php?phone=' + str(self.PHONE) + '&apikey=' + str(
            self.APIKEY) + '&text=' + str(message).replace(" ", "+")
        try:
            response = requests.get(url, timeout=5)
        except Exception as e:
            print(url, f"request GET {url} failed: ", e)
            return False
        return response



class Telegram:
    def __init__(self, username):
        self.USERNAME = username

    def send_message(self, message):
        url = 'https://api.callmebot.com/text.php?user=' + str(self.USERNAME) +\
              '&text=' + str(message).replace(" ", "+")
        try:
            response = requests.get(url, timeout=5)
        except Exception as e:
            print(url, f"request GET {url} failed: ", e)
            return False
        return response
