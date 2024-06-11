import asyncio
import shared
from lib.stepper_doser_math import to_float
try:
    from ulab import numpy as np
except ImportError:
    import numpy as np


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