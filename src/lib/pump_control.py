import json
import time

from lib.exec_code import evaluate_expression
from lib.mqtt_worker import mqtt_stats
from lib.stepper_doser_math import move_with_rpm

try:
    from ulab import numpy as np
    import uasyncio as asyncio
    from lib.async_queue import Queue as asyncQueue
except ImportError:
    import numpy as np
    import asyncio as asyncio
    from asyncio.queues import Queue as asyncQueue

import shared


def to_float(arr):
    if isinstance(arr, np.ndarray):
        # If it's a single-item NumPy array, extract the item and return
        return arr[0]
    else:
        return arr


async def stepper_run(mks, desired_rpm_rate, duration, direction, rpm_table, expression=False,
                      pump_dose=0, pump_id=None, weekdays=None):
    if weekdays is None:
        weekdays = [0, 1, 2, 3, 4, 5, 6]

    async def change_remaining():
        print("id:", pump_id, " dose:", pump_dose)
        if pump_dose and pump_id is not None:
            _remaining = shared.storage[f"remaining{pump_id}"] - pump_dose
            _remaining = max(0, _remaining)
            _storage = shared.storage[f"pump{pump_id}"]
            shared.storage[f"remaining{pump_id}"] = _remaining
            print("Updated storage:", shared.storage)

            if shared.mqtt_settings["broker"]:
                print("Publish to mqtt")
                _topic = f"{shared.doser_topic}/pump{pump_id}"
                _data = {"id": pump_id, "name": shared.settings["names"][pump_id - 1],
                         "dose": pump_dose, "duration": duration,
                         "remain": shared.storage[f"remaining{pump_id}"], "storage": shared.storage[f"pump{pump_id}"]}
                print("data", _data)
                print({"topic": _topic, "data": _data})
                try:
                    await shared.mqtt_worker.add_message_to_publish(f"pump{pump_id}", json.dumps(_data))
                except Exception as e:
                    print(e)

            # Format the time with leading zeros
            formatted_time = shared.get_time()

            msg = ""
            if shared.settings["whatsapp_dose_msg"] or shared.settings["telegram_dose_msg"]:
                msg += f"{formatted_time} Pump{pump_id} {shared.settings['names'][pump_id - 1]}: "
                msg += f"Dose {pump_dose}mL/{duration}sec, {_remaining}/{_storage}mL"
            if msg and shared.settings["telegram_dose_msg"]:
                await shared.telegram_worker.add_message(msg)
            if msg and shared.settings["whatsapp_dose_msg"]:
                print("MSG:", msg)
                await shared.whatsapp_worker.add_message(msg)

            msg = ""
            if (shared.settings["whatsapp_empty_container_msg"] or shared.settings["telegram_empty_container_msg"]) \
                    and shared.storage[f"pump{pump_id}"]:
                filling_percentage = round(_remaining / shared.storage[f"pump{pump_id}"] * 100, 1)
                if 0 < filling_percentage < shared.settings["empty_container_lvl"]:
                    msg += f"{formatted_time} Pump{pump_id} {shared.settings['names'][pump_id - 1]}: "
                    msg += f"Container {filling_percentage}% full"
                elif filling_percentage == 0:
                    msg += f"{formatted_time} Pump{pump_id} {shared.settings['names'][pump_id - 1]}: Container empty"
            if msg and shared.settings["telegram_empty_container_msg"]:
                await shared.telegram_worker.add_message(msg)
            if msg and shared.settings["whatsapp_empty_container_msg"]:
                await shared.whatsapp_worker.add_message(msg)

    wday = time.localtime()[6]
    print(f"Check weekdays: {wday} in {weekdays}")
    if wday not in weekdays:
        print("Skip dosing job")
        return

    print(f"Desired {desired_rpm_rate}rpm, mstep")
    if shared.settings["inversion"][pump_id - 1]:
        direction = 0 if direction == 1 else 1

    if expression:
        print("Check expression: ", expression)
        result, logs = evaluate_expression(expression, globals())
        if result:
            print(f"Limits check pass")
            calc_time = move_with_rpm(mks, desired_rpm_rate, duration, rpm_table, direction)
            await change_remaining()
            return [calc_time]
    else:
        calc_time = move_with_rpm(mks, desired_rpm_rate, duration, rpm_table, direction)
        await change_remaining()
        await asyncio.sleep(1)
        return [calc_time]
    print(f"Limits check not pass, skip dosing")
    return False


async def stepper_stop(mks):
    print(f"Stop {id} stepper")
    return mks.stop()


class CommandHandler:
    @staticmethod
    def check_dose_parameters(cmd):
        if all(key in cmd for key in ["id", "amount", "duration", "direction"]):
            # Check the range and validity of each parameter
            return (1 <= int(cmd["id"]) <= shared.PUMP_NUM and
                    int(cmd["amount"]) > 0 and
                    1 <= int(cmd["duration"]) <= 3600 and
                    int(cmd["direction"]) in [0, 1])
        return False

    @staticmethod
    def check_run_parameters(cmd):
        if all(key in cmd for key in ["id", "rpm", "duration", "direction"]):
            # Check the range and validity of each parameter
            return (1 <= int(cmd["id"]) <= shared.PUMP_NUM and
                    0.5 <= int(cmd["rpm"]) <= 1000 and
                    1 <= int(cmd["duration"]) <= 3600 and
                    int(cmd["direction"]) in [0, 1])
        return False

    @staticmethod
    def check_stop_parameters(cmd):
        if "id" in cmd:
            return 1 <= int(cmd["id"]) <= shared.PUMP_NUM
        return False

    @staticmethod
    def check_refill_parameters(cmd):
        if "id" in cmd:
            if "storage" in cmd:
                return (1 <= int(cmd["id"]) <= shared.PUMP_NUM and
                        0 <= int(cmd["storage"]) < 65535)
            else:
                return 1 <= cmd["id"] <= shared.PUMP_NUM
        return False

    async def dose(self, command):
        print(f"Handling dosing command: {command}")
        if not self.check_dose_parameters(command):
            print("Dose cmd parameter error: ", command)
            return
        desired_flow = command["amount"] * (60 / command["duration"])
        print(f"Desired flow: {round(desired_flow, 2)}")
        print(f"Direction: {command['direction']}")
        desired_rpm_rate = np.interp(desired_flow, shared.chart_points[f"pump{command['id']}"][1],
                                     shared.chart_points[f"pump{command['id']}"][0])
        print("Calculated RPM: ", desired_rpm_rate)
        await shared.command_buffer.add_command(stepper_run, None, shared.mks_dict[f"mks{command['id']}"],
                                                desired_rpm_rate,
                                                command['duration'], command['direction'], shared.rpm_table,
                                                shared.limits_settings[str(command['id'])], pump_dose=command["amount"],
                                                pump_id=int(command['id']))

    async def run(self, command):
        print(f"Handling run command: {command}")
        if not self.check_run_parameters(command):
            print("Run cmd parameter error: ", command)
            return
        print(f"Direction: {command['direction']}")
        desired_rpm_rate = command['rpm']
        print("Desired RPM: ", desired_rpm_rate)
        await shared.command_buffer.add_command(stepper_run, None, shared.mks_dict[f"mks{command['id']}"],
                                                desired_rpm_rate,
                                                command['duration'], command['direction'], shared.rpm_table,
                                                shared.limits_settings[str(command['id'])], pump_dose=None,
                                                pump_id=int(command['id']))

    async def stop(self, command):
        print(f"Handling stop command: {command}")
        if not self.check_stop_parameters(command):
            print("Stop cmd parameter error: ", command)
            return
        print(f"Stop pump{command['id']}")
        await shared.command_buffer.add_command(stepper_stop, None, shared.mks_dict[f"mks{command['id']}"])

    async def refill(self, command):
        print(f"Handling refill command: {command}")
        if not self.check_refill_parameters(command):
            print("Refill cmd parameter error: ", command)
        print(f"Refilling pump{command['id']} storage")
        if "storage" in command:
            shared.storage[f"pump{command['id']}"] = int(command['storage'])
        shared.storage[f"remaining{command['id']}"] = shared.storage[f"pump{command['id']}"]
        _pump_id = command['id']
        _topic = f"{shared.doser_topic}/pump{_pump_id}"
        _data = {"id": _pump_id, "name": shared.settings["names"][_pump_id - 1], "dose": 0, "duration": 1,
                 "remain": shared.storage[f"remaining{_pump_id}"], "storage": shared.storage[f"pump{_pump_id}"]}
        await shared.mqtt_worker.add_message_to_publish(f"pump{command['id']}", json.dumps(_data))
        await shared.mqtt_worker.publish_stats(
            mqtt_stats(version=shared.RELEASE_TAG, hostname=shared.settings["hostname"], names=shared.settings["names"],
                       number=shared.PUMP_NUM, current=shared.settings["pumps_current"],
                       inversion=shared.settings["inversion"],
                       storage=shared.storage, max_pumps=shared.MAX_PUMPS))


class Servo42c:
    def __int__(self, driver):
        print()


class PumpController:
    def __init__(self, driver):
        self.driver = driver
        self.buffer = asyncQueue()

    @staticmethod
    def dose(command):
        # Implement the dosing logic for the pump
        print(f"Dosing with command: {command}")
        # Implement control logic
        # Placeholder for actual dosing command to hardware
        asyncio.create_task(shared.mqtt_worker.add_message_to_publish("/status/dose",
                                                                      {"status": "completed", "command": command}))
        shared.whatsapp_worker.add_message("Dose completed successfully.")
        shared.telegram_worker.add_message("Dose completed successfully.")

    @staticmethod
    def run(command):
        # Implement the running logic for the pump
        print(f"Running with command: {command}")

    @staticmethod
    def stop(command):
        # Implement the stopping logic for the pump
        print(f"Stopping with command: {command}")
        # Implement control logic

    @staticmethod
    def refill(command):
        # Implement the refilling logic for the pump
        print(f"Refilling with command: {command}")
        # Implement control logic

    @staticmethod
    async def worker():
        try:
            while True:
                print("Process commands")

                await asyncio.sleep(1)

        except Exception as e:
            print(f'MQTT connection error: {e}')
