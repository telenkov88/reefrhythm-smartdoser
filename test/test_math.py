import time

import pytest
import sys
from lib.servo42c import *
from lib.stepper_doser_math import *


def lookup(target_device, command):
   return target_device.exec("print(" + command + ")").decode("utf-8").strip()


def free_mem(pyb):
    pyb.exec("gc.collect()")
    ret = int(lookup(pyb, "gc.mem_free()"))
    print(f"free mem: {ret // 1024}Kb")
    return ret // 1024


def test_make_rpm_table(pyboard):
    esp32 = pyboard
    esp32.exec("from lib.servo42c import *")
    esp32.exec("from lib.stepper_doser_math import *")
    esp32.exec("np.set_printoptions(threshold=sys.maxsize)")
    print("\r\n")
    free_mem(esp32)

    start_mem = free_mem(esp32)
    start_time = time.time()
    esp32.exec_raw("rpm_table = make_rpm_table(regenerate=True)", timeout=600)
    end_mem = free_mem(esp32)
    print(f"Table size {abs(end_mem-start_mem)}Kb, Time: {time.time()-start_time} Sec")

    import numpy as np
    def load_from_string(array_str, dtype):
        import re
        # Use regular expression to find all numbers in the string
        numbers = re.findall(r"[\d\.]+", array_str)

        # Convert found strings to floats
        float_numbers = [float(num) for num in numbers]

        # Create a NumPy array from the list of floats
        loaded_array = np.array(float_numbers, dtype=dtype)
        return loaded_array

    rpm_table = load_from_string(lookup(esp32, "rpm_table[0]"), dtype=float)
    mstep_table = load_from_string(lookup(esp32, "rpm_table[1]"), dtype=np.uint8)
    speed_table = load_from_string(lookup(esp32, "rpm_table[2]"), dtype=np.uint8)

    for index in range(0, len(rpm_table)):
        print(f"RPM: {rpm_table[index]:<8}", end=' ')
        print(
            f"RealRPM: {round(calc_real_rpm(int(mstep_table[index]), int(speed_table[index])), 4) :<8},"
            f" MSTEP: {mstep_table[index]:<5}, SPEED: {speed_table[index]:<5}")


# Check accuracy in RPM matrix
def test_extrapolate_calibration_points(pyboard):
    import time
    import numpy as np
    print("\n")
    points = [(0.58, 0.107), (1, 0.17), (5, 0.9), (10, 1.8), (20, 3.5),(50, 9),(100, 18),(300, 54.9), (600, 113.4), (1000, 180)]

    esp32 = pyboard
    free_mem(esp32)
    esp32.exec(f"points = {points}")
    ret = esp32.exec("print(points)")
    print(ret)
    esp32.exec("from lib.servo42c import *")
    esp32.exec("from lib.stepper_doser_math import *")
    start_time = time.time()
    esp32.exec("extrapolated_rpm_values, extrapolated_flow_rate_values = extrapolate_flow_rate(points, 4)")
    print("Extrapolation: --- %s seconds ---" % (time.time() - start_time))
    free_mem(esp32)

    esp32.exec("np.set_printoptions(threshold=sys.maxsize)")
    extrapolated_rpm_values = esp32.exec("print(extrapolated_rpm_values)").decode('utf-8').strip()
    elements = extrapolated_rpm_values.strip('array([').strip('], dtype=float32)').split(', ')
    extrapolated_rpm_values = np.array(elements, dtype=np.float32)

    extrapolated_flow_rate_values = esp32.exec("print(extrapolated_flow_rate_values)").decode("utf-8").strip()
    elements = extrapolated_flow_rate_values.strip('array([').strip('], dtype=float32)').split(', ')
    extrapolated_flow_rate_values = np.array(elements, dtype=np.float32)

    esp32.exec("desired_flow = 100")

    start_time = time.time()
    esp32.exec("desired_rpm_rate = np.interp(desired_flow, extrapolated_flow_rate_values, extrapolated_rpm_values)")
    print("Finding desired rpm rate: --- %s seconds ---" % (time.time() - start_time))
    ret = float(esp32.exec("print(desired_rpm_rate[0])").decode("utf-8").strip())
    print(f"\nRPM rate is {ret} for 100 flow ml/min")
    free_mem(esp32)

    # Plot the data
    import matplotlib.pyplot as plt
    plt.plot(extrapolated_rpm_values, extrapolated_flow_rate_values, label='Extrapolated Flow Rate')
    plt.scatter(*zip(*points), color='red', label='Calibration Points')
    plt.scatter(ret, 100, color='green', label='Desired Flow Rate')
    plt.xlabel('RPM')
    plt.ylabel('Flow Rate (ml/min)')
    plt.title('Extrapolated Flow Rate vs RPM')
    plt.legend()
    plt.grid(True)

    # Save the plot as a JPEG image
    plt.savefig('plot.jpg', format='jpeg')

    plt.show()


# Check accuracy in RPM matrix
def test_find_closest_rpm(pyboard):
    esp32 = pyboard
    esp32.exec("from lib.servo42c import *")
    esp32.exec("np.set_printoptions(threshold=sys.maxsize)")
    free_mem(esp32)

    esp32.exec(f"")
    esp32.exec(f"filtered_values = make_rpm_table()")
    free_mem(esp32)

    print(f"RPM      Closest RPM  MSTEP SPEED  Error %   Calc Time")
    max_error=0
    max_time=0
    for desired_rpm in np.arange(RPM_STEP * 5, 1000 + RPM_STEP, RPM_STEP):
        start_time = time.time()
        combination = lookup(esp32, f"find_combination({desired_rpm}, filtered_values)").lstrip("(").rstrip(")").split(",")
        end_time = time.time()
        rpm = float(combination[0])
        mstep = int(combination[1])
        speed = int(combination[2])
        real_speed = calc_real_rpm(mstep, speed)
        round_rpm = round(float(rpm), 3)

        rpm_error = (1 - (desired_rpm - abs(desired_rpm - real_speed)) / desired_rpm) * 100
        if rpm_error > max_error:
            max_error = rpm_error
        max_error = max(max_error, rpm_error)
        max_time = max((end_time-start_time), max_time)

        rpm_error = round(rpm_error, 2)
        print(f"{desired_rpm: <7}  {round_rpm: <7}       {mstep: <3}    {speed: <3}  {rpm_error:<6}       "
              f"{round(end_time- start_time, 3): <6}")
        assert rpm_error <= 1.3
    print(f"Max error: {round(max_error, 3)}")
    print(f"Max time:  {round(max_time, 3)}")