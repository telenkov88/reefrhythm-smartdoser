import pytest
from config import port as pyport


def pytest_addoption(parser):
    parser.addoption("--deploy", action="store", default="True")
    parser.addoption("--stepper_addr", action="store", default="0")


@pytest.fixture
def input_value():
    input = 39
    return input


def lookup(target_device, command):
    return target_device.exec("print(" + command + ")").decode("utf-8").strip()


@pytest.fixture(scope='session')
def pyboard(request):
    import pyboard, os
    pyb = pyboard.Pyboard(pyport, 115200)
    pyb.enter_raw_repl()
    pyb.exec("import sys, os, gc")
    print("[HOST]:")
    for _ in os.listdir("../src/"):
        print(_)
    print("\n[DEBUG]: sys.implementation = " + lookup(pyb, "sys.implementation"))
    print("[DEBUG]: sys.implementation._machine = " + lookup(pyb, "sys.implementation._machine"))
    print("[DEBUG]: sys.implementation.version = " + lookup(pyb, "sys.implementation.version"))

    if request.config.getoption("deploy") == "True":
        print("Copy files to pyboard")
        print("\n[DEBUG]: local files: = " + lookup(pyb, " os.listdir()"))

        files = ["./rpm_table.json",
                 "./rpm_table.txt",
                 "./debug.py",
                 "./captive_portal.py",
                 "./config/pin_config.py",
                 "./config/calibration_points.json",
                 "./lib/servo42c.py",
                 "./lib/stepper_doser_math.py",
                 "./lib/microdot/microdot.py",
                 "./lib/microdot/sse.py",
                 "./static/calibration.html,"
                 "./static/doser.html",
                 "./static/ota-upgrade.html",
                 "./static/captive_portal.html",
                 "./static/favicon/android-chrome-192x192.png",
                 "./static/favicon/android-chrome-512x512.png",
                 "./static/favicon/apple-touch-icon.png",
                 "./static/favicon/favicon.ico",
                 "./static/favicon/favicon-16x16.png",
                 "./static/favicon/favicon-32x32.png",
                 "./static/favicon/site.webmanifest"
                 ]

        directories = [
            "./config",
            "./lib",
            "./lib/microdot",
            "./static",
            "./static/favicon"]

        try:
            pyb.fs_stat('boot.py')
            pyb.fs_rm('boot.py')
        except FileNotFoundError:
            print(f"{'boot.py'} not exist")

        for file in files:
            if file:
                try:
                    pyb.fs_stat(file)
                    pyb.fs_rm(file)
                except FileNotFoundError:
                    print(f"{file} not exist")
        for dir in directories:
            if dir:
                try:
                    pyb.fs_stat(dir)
                except FileNotFoundError:
                    pyb.fs_mkdir(dir)

        pyb.fs_put("./debug.py", "./debug.py")
        pyb.fs_put("../web.py", "./web.py")
        pyb.fs_put("../lib/servo42c.py", "./lib/servo42c.py")
        pyb.fs_put("../lib/stepper_doser_math.py", "./lib/stepper_doser_math.py")
        pyb.fs_put("../connect_wifi.py", "./connect_wifi.py")
        pyb.fs_put("../static/calibration.html", "./static/calibration.html")
        pyb.fs_put("../static/captive_portal.html", "./static/captive_portal.html")
        pyb.fs_put("../static/doser.html", "./static/doser.html")
        pyb.fs_put("../static/ota-upgrade.html", "./static/ota-upgrade.html")
        pyb.fs_put("../static/favicon/android-chrome-192x192.png", "./static/favicon/android-chrome-192x192.png")
        pyb.fs_put("../static/favicon/android-chrome-512x512.png", "./static/favicon/android-chrome-512x512.png")
        pyb.fs_put("../static/favicon/apple-touch-icon.png", "./static/favicon/apple-touch-icon.png")
        pyb.fs_put("../static/favicon/favicon.ico", "./static/favicon/favicon.ico")
        #pyb.fs_put("../static/favicon-32x32.png", "./static/favicon-32x32.png")
        #pyb.fs_put("../static/favicon-16x16.png", "./static/favicon-16x16.png")
        pyb.fs_put("../static/favicon/site.webmanifest", "./static/favicon/site.webmanifest")

        pyb.fs_put("../lib/microdot/microdot.py", "./lib/microdot/microdot.py")
        pyb.fs_put("../lib/microdot/sse.py", "./lib/microdot/sse.py")
        pyb.fs_put("../config/pin_config.py", "./config/pin_config.py")
        pyb.fs_put("../config/calibration_points.json", "./config/calibration_points.json")
    elif request.config.getoption("deploy") == "servo42c":
        try:
            pyb.fs_stat('./lib/servo42c.py')
            pyb.fs_rm('./lib/servo42c.py')
        except FileNotFoundError:
            print(f"{'boot.py'} not exist")
        print("deploy servo42c lib")
        pyb.fs_put("../lib/servo42c.py", "./lib/servo42c.py")

    print("\n[DEBUG]: local files: = " + lookup(pyb, " os.listdir()"))
    print("\n[DEBUG]: Lib dir: " + lookup(pyb, " os.listdir('./lib')"))
    print("Finished file transfer")
    yield pyb
    pyb.exit_raw_repl()


@pytest.fixture(scope='module')
def rpm_table(pyboard, request):
    pyboard.exec("from lib.servo42c import *")
    pyboard.exec("from lib.stepper_doser_math import *")
    pyboard.exec("command_buffer = CommandBuffer()")
    pyboard.exec("from config.pin_config import *")
    pyboard.exec("np.set_printoptions(threshold=sys.maxsize)")
    addr = 0  # Stepper motor UART addr
    pyboard.exec(f"")
    pyboard.exec_raw("rpm_table = make_rpm_table()", timeout=600)
    pyboard.exec("uart = UART(1)")
    pyboard.exec("uart.init(baudrate=38400, rx=rx_pin, tx=tx_pin, timeout=100)")
    pyboard.exec(f"mks = Servo42c(uart, {int(request.config.getoption('stepper_addr'))}, mstep=1)")
    pyboard.exec("mks.set_current(1000)")
