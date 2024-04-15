import sys

import pytest
from config import port as pyport
import os


def pytest_addoption(parser):
    parser.addoption("--deploy", action="store", default="True")
    parser.addoption("--stepper_addr", action="store", default="0")


def list_files(path):
    # Check if the path exists
    if os.path.exists(path):
        # List all files in the directory
        files = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
        return files
    else:
        print("The specified path does not exist.")

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

        for dir in directories:
            if dir:
                try:
                    pyb.fs_stat(dir)
                except FileNotFoundError:
                    pyb.fs_mkdir(dir)

        libs = list_files("../src/lib")
        configs = list_files("../src/config")
        statics = list_files("../src/static")

        for file in libs:
            pyb.fs_put(f"../src/lib/{file}", f"./lib/{file}")
        for file in configs:
            pyb.fs_put(f"../src/config/{file}", f"./config/{file}")
        for file in statics:
            if "html.gz" in file:
                pyb.fs_put(f"../src/static/{file}", f"./static/{file}")

    elif request.config.getoption("deploy") == "servo42c":
        #try:
        #    pyb.fs_stat('./lib/servo42c.py')
        #    pyb.fs_rm('./lib/servo42c.py')
        #except FileNotFoundError:
        #    print(f"{'boot.py'} not exist")
        print("deploy servo42c lib")
        pyb.fs_put("../src/lib/servo42c.py", "./lib/servo42c.py")

    print("\n[DEBUG]: local files: = " + lookup(pyb, " os.listdir()"))
    print("\n[DEBUG]: Lib dir: " + lookup(pyb, " os.listdir('./lib')"))
    print("Finished file transfer")
    yield pyb
    pyb.exit_raw_repl()


@pytest.fixture(scope='module')
def rpm_table(pyboard, request):
    pyboard.exec("from load_configs import *")
    pyboard.exec("np.set_printoptions(threshold=sys.maxsize)")
    pyboard.exec(f"mks = Servo42c(uart, {int(request.config.getoption('stepper_addr'))}, mstep=1)")
    pyboard.exec("mks.set_current(1000)")
