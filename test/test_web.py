import time

import pytest
import sys

import_libs = ["import gc, os, sys, network"]


@pytest.fixture(scope="function")
def connect_wifi(pyboard):
    pyb = pyboard
    pyb.exec("gc.collect()")
    for lib in import_libs:
        pyb.exec(lib)
    free_mem(pyb)
    print("start wi-fi")
    pyb.exec("from connect_wifi import *")
    print("wait for connection")
    pyb.exec("wait_connection(nic)")
    yield pyb


def lookup(target_device, command):
   return target_device.exec("print(" + command + ")").decode("utf-8").strip()


def free_mem(pyb):
    pyb.exec("gc.collect()")
    ret = int(lookup(pyb, "gc.mem_free()"))
    print(f"free mem: {ret // 1024}Kb")
    return ret // 1024


def test_start_server(connect_wifi):
    pyb = connect_wifi
    ip = lookup(pyb, "nic.ifconfig()[0]")
    print(f"IP: {ip}")
    print("Start Server")

    import urllib3, json
    import threading

    def start_web(pyb):
        print("Web server is starting...")
        pyb.exec("import web")
        pyb.exec("loop = asyncio.get_event_loop()")
        pyb.exec("loop.run_forever()")

    from pyboard import PyboardError

    web_server_thread = threading.Thread(target=start_web, args=(pyb,))
    web_server_thread.start()

    time.sleep(0.5)
    url = f"http://{ip}/memfree"
    for _ in range(0, 9):
        try:
            def load_url(url):
                http = urllib3.PoolManager()
                response = http.request('GET', url)
                data = response.data
                return json.loads(data)["free_mem"]
            mem_onstart = load_url(url)
            print(f'Free memory on start: {mem_onstart}Kb')
            mem = load_url(url)
            print(f'Free memory after garbage collection: {mem}Kb')

            break
        except Exception as e:
            print(f"Failed to load {url}\n {e}")
            time.sleep(1)

    try:
        web_server_thread.join()
    except PyboardError:
        print("pyboard released")
    try:
        assert mem >= 10, "ESP32 low in memory"
    except:
        pytest.fail(f"Failed to get free memory from {url}")


def test_mode_main(pyboard):
    pytest.skip("only for debug")
    pyb = pyboard
    pyb.fs_put("./debug_main.py", "./boot.py")


def test_wifi_ap(pyboard):
    pyb = pyboard
    print("Test wifi AP")