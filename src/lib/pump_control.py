import json
import time

from lib.exec_code import evaluate_expression
from lib.mqtt_worker import mqtt_stats
from lib.stepper_doser_math import move_with_rpm

try:
    from ulab import numpy as np
    import uasyncio as asyncio
except ImportError:
    import numpy as np
    import asyncio as asyncio

import shared


def to_float(arr):
    if isinstance(arr, np.ndarray):
        # If it's a single-item NumPy array, extract the item and return
        return arr[0]
    else:
        return arr


async def stepper_run(mks, desired_rpm_rate, execution_time, direction, rpm_table, expression=False,
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
                _data = {"id": pump_id, "name": shared.settings["names"][pump_id - 1], "dose": pump_dose,
                         "remain": shared.storage[f"remaining{pump_id}"], "storage": shared.storage[f"pump{pump_id}"]}
                print("data", _data)
                print({"topic": _topic, "data": _data})
                try:
                    shared.mqtt_worker.add_message_to_publish(f"pump{pump_id}", json.dumps(_data))
                except Exception as e:
                    print(e)

            # Format the time with leading zeros
            formatted_time = shared.get_time()

            msg = ""
            if shared.settings["whatsapp_dose_msg"] or shared.settings["telegram_dose_msg"]:
                msg += f"{formatted_time} Pump{pump_id} {shared.settings['names'][pump_id - 1]}: "
                msg += f"Dose {pump_dose}mL/{execution_time}sec, {_remaining}/{_storage}mL"
            if msg and shared.settings["telegram_dose_msg"]:
                await shared.telegram_worker.add_message(msg)
            if msg and shared.settings["whatsapp_dose_msg"]:
                print("MSG:", msg)
                await shared.whatsapp_worker.add_message(msg)

            msg = ""
            if (shared.settings["whatsapp_empty_container_msg"] or shared.settings["telegram_empty_container_msg"]) and \
                    shared.storage[f"pump{pump_id}"]:
                filling_percentage = round(_remaining / shared.storage[f"pump{pump_id}"] * 100, 1)
                if 0 < filling_percentage < shared.settings["empty_container_lvl"]:
                    msg += f"{formatted_time} Pump{pump_id} {shared.settings['names'][pump_id - 1]}: Container {filling_percentage}% full"
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
            calc_time = move_with_rpm(mks, desired_rpm_rate, execution_time, rpm_table, direction)
            await change_remaining()
            return [calc_time]
    else:
        calc_time = move_with_rpm(mks, desired_rpm_rate, execution_time, rpm_table, direction)
        await change_remaining()
        await asyncio.sleep(1)
        return [calc_time]
    print(f"Limits check not pass, skip dosing")
    return False


async def stepper_stop(mks):
    print(f"Stop {id} stepper")
    return mks.stop()


class CommandHandler:
    def check_dose_parameters(self, cmd):
        if all(key in cmd for key in ["id", "amount", "duration", "direction"]):
            # Check the range and validity of each parameter
            return (1 <= cmd["id"] <= shared.PUMP_NUM and
                    cmd["amount"] > 0 and
                    1 <= cmd["duration"] <= 3600 and
                    cmd["direction"] in [0, 1])
        return False

    def check_run_parameters(self, cmd):
        if all(key in cmd for key in ["id", "rpm", "duration", "direction"]):
            # Check the range and validity of each parameter
            return (1 <= cmd["id"] <= shared.PUMP_NUM and
                    0.5 <= cmd["rpm"] <= 1000 and
                    1 <= cmd["duration"] <= 3600 and
                    cmd["direction"] in [0, 1])
        return False

    def check_stop_parameters(self, cmd):
        if "id" in cmd:
            return 1 <= cmd["id"] <= shared.PUMP_NUM
        return False

    def check_refill_parameters(self, cmd):
        if "id" in cmd:
            if "storage" in cmd:
                return (1 <= cmd["id"] <= shared.PUMP_NUM and
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
        _data = {"id": _pump_id, "name": shared.settings["names"][_pump_id - 1], "dose": 0,
                 "remain": shared.storage[f"remaining{_pump_id}"], "storage": shared.storage[f"pump{_pump_id}"]}
        shared.mqtt_worker.add_message_to_publish(f"pump{command['id']}", json.dumps(_data))
        shared.mqtt_worker.publish_stats(
            mqtt_stats(version=shared.RELEASE_TAG, hostname=shared.settings["hostname"], names=shared.settings["names"],
                       number=shared.PUMP_NUM, current=shared.settings["pumps_current"],
                       inversion=shared.settings["inversion"],
                       storage=shared.storage, max_pumps=shared.MAX_PUMPS))


async def analog_control_worker():
    while not shared.adc_sampler_started:
        print("Wait for adc sampler finish firts cycle")
        await asyncio.sleep(0.1)
    print("Init adc worker")
    print("adc_dict:", shared.adc_dict)
    # Init Pumps
    adc_buffer_values = {}
    for i, en in enumerate(shared.analog_en):
        if en and len(shared.analog_settings[f"pump{i + 1}"]["points"]) >= 2:
            if shared.analog_settings[f"pump{i + 1}"]["pin"] != 99:
                print("adc_buffer_values append ", shared.adc_dict[shared.analog_settings[f"pump{i + 1}"]["pin"]])
                adc_buffer_values[i] = [shared.adc_dict[shared.analog_settings[f"pump{i + 1}"]["pin"]]]
            else:
                adc_buffer_values[i] = [4095]
        else:
            adc_buffer_values[i] = [0]

    print("ota_lock:", shared.ota_lock)
    print(adc_buffer_values)
    while True:
        print("Analog worker cycle")
        while shared.ota_lock:
            await asyncio.sleep(200)

        for i, en in enumerate(shared.analog_en):
            if en and len(shared.analog_settings[f"pump{i + 1}"]["points"]) >= 2:
                print(f"\r\n================\r\nRun pump{i + 1}, PIN", shared.analog_settings[f"pump{i + 1}"]["pin"])
                print(adc_buffer_values[i])
                adc_average = sum(adc_buffer_values[i]) // len(adc_buffer_values[i])
                print("ADC value: ", adc_average)
                adc_signal = adc_average / 40.95
                print(f"Signal: {adc_signal}")
                signals, flow_rates = zip(*shared.analog_chart_points[f"pump{i + 1}"])
                desired_flow = to_float(np.interp(adc_signal, signals, flow_rates))
                amount = desired_flow * shared.settings["analog_period"] / 60
                print("Desired flow", desired_flow)
                print("Amount:", amount)
                if desired_flow >= 0.01:
                    desired_rpm_rate = to_float(
                        np.interp(desired_flow, shared.chart_points[f"pump{i + 1}"][1],
                                  shared.chart_points[f"pump{i + 1}"][0]))

                    await shared.command_buffer.add_command(stepper_run, None, shared.mks_dict[f"mks{i + 1}"],
                                                            desired_rpm_rate,
                                                            shared.settings["analog_period"] + 5,
                                                            shared.analog_settings[f"pump{i + 1}"]["dir"],
                                                            shared.rpm_table,
                                                            shared.limits_settings[str(i + 1)], pump_dose=amount,
                                                            pump_id=(i + 1))
        for _ in range(len(shared.analog_en)):
            adc_buffer_values[_] = []
        for x in range(0, shared.settings["analog_period"]):
            for i, en in enumerate(shared.analog_en):
                if en and shared.analog_settings[f"pump{i + 1}"]["pin"] != 99:
                    adc_buffer_values[i].append(shared.adc_dict[shared.analog_settings[f"pump{i + 1}"]["pin"]])
                else:
                    adc_buffer_values[i] = [4095]

            await asyncio.sleep(1)


class PumpController:
    def __init__(self, mqtt_worker, whatsapp_worker, telegram_worker):
        self.mqtt_worker = mqtt_worker
        self.whatsapp_worker = whatsapp_worker
        self.telegram_worker = telegram_worker
        self.buffer = []
        self.lock = asyncio.Lock()

    def dose(self, command):
        # Implement the dosing logic for the pump
        print(f"Dosing with command: {command}")
        # Implement control logic
        # Placeholder for actual dosing command to hardware
        self.mqtt_worker.add_message_to_publish("/status/dose", {"status": "completed", "command": command})
        self.whatsapp_worker.add_message("Dose completed successfully.")
        self.telegram_worker.add_message("Dose completed successfully.")

    def run(self, command):
        # Implement the running logic for the pump
        print(f"Running with command: {command}")

    def stop(self, command):
        # Implement the stopping logic for the pump
        print(f"Stopping with command: {command}")
        # Implement control logic

    def refill(self, command):
        # Implement the refilling logic for the pump
        print(f"Refilling with command: {command}")
        # Implement control logic

    async def worker(self):
        try:
            while True:
                print("Process commands")

                await asyncio.sleep(1)

        except Exception as e:
            print(f'MQTT connection error: {e}')
