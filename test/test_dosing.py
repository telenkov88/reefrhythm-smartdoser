import time
from numpy import int64
import os
from src.lib.servo42c import *
from src.lib.stepper_doser_math import *
import pytest

test_number = 100


def lookup(target_device, command):
    print(command)
    return target_device.exec("print(" + command + ")").decode("utf-8").strip()


def free_mem(pyb):
    pyb.exec("gc.collect()")
    ret = int(lookup(pyb, "gc.mem_free()"))
    print(f"free mem: {ret // 1024}Kb")
    return ret // 1024


def read_encoder(pb):
    def values_from_str(string):
        string = string.lstrip('(').rstrip(')').split(',')
        return int(string[0]), int(string[1])

    out = lookup(pb, f"mks.read_encoder(debug=True)").split(os.linesep)[-1]
    assert "False" not in out
    carry, value = values_from_str(out)
    print(carry, value)
    return int64(carry * 65536 + value)


def test_set_mstep(rpm_table, pyboard):
    esp32 = pyboard
    mstep = lookup(esp32, "mks.set_mstep(1, force=True)")
    print(mstep)
    mstep = lookup(esp32, "mks.set_mstep(127, force=True)")
    print(mstep)
    mstep = lookup(esp32, "mks.set_mstep(255, force=True)")
    print(mstep)


def test_read_encoder(rpm_table, pyboard):
    esp32 = pyboard
    encoder_value = read_encoder(esp32)
    mstep = lookup(esp32, "mks.set_mstep(1, force=True)")
    print(mstep)
    esp32.exec("mks.make_steps(200, 1, 0)")
    time.sleep(2)

    new_encoder_value = read_encoder(esp32)

    delta = abs(encoder_value - new_encoder_value)
    print("Encoder delta: ", delta)
    assert 65536 - 365 < abs(delta) < 65536 + 365, "Encoder accuracy lower than 1%"


def test_mks_read_pulses(rpm_table, pyboard):
    print()
    esp32 = pyboard
    out = lookup(esp32, "mks.read_pulses()")
    start_pulses = out.split(os.linesep)[-1]
    print("Start pulses:", start_pulses)

    assert start_pulses != 'None'

    print("\nRun 100 pulses:")
    esp32.exec("mks.make_steps(100, 1, 1)")
    out = lookup(esp32, "mks.read_pulses()")
    new_pulses = out.split(os.linesep)[-1]

    print("New pulses: ", new_pulses)
    assert int(start_pulses) == int(new_pulses) - 100


def test_motor_stops(rpm_table, pyboard):
    esp32 = pyboard
    esp32.exec(f"mks.set_mstep(16)")

    out = lookup(esp32, "mks.stop()")
    print("Return:", out)
    assert 'True' in out

    print("Check stop with running motor")
    esp32.exec("mks.move(1, 1)")
    time.sleep(2)
    out = lookup(esp32, "mks.stop()")
    start_pulses = lookup(esp32, "mks.read_pulses()").split(os.linesep)[-1]
    time.sleep(1)
    end_pulses = lookup(esp32, "mks.read_pulses()").split(os.linesep)[-1]
    print("Return:", out)
    assert 'True' in out
    assert start_pulses == end_pulses, "motor spinning!"


@pytest.mark.parametrize("rpm", [0.5, 44.5, 1, 65.5, 3, 35])
@pytest.mark.parametrize("timeout", [5])
def test_mks_make_steps(rpm_table, pyboard, rpm, timeout):
    print('\n', '-' * 50, '\n')
    print(f"Run motor {rpm}RPM for {timeout}s")
    esp32 = pyboard

    combination = lookup(esp32, f"find_combination({rpm}, rpm_table)").lstrip("(").rstrip(")").split(",")
    rpm = float(combination[0])
    mstep = int(combination[1])
    speed = int(combination[2])

    steps = lookup(esp32, f"calc_steps(mks, {rpm}, {mstep}, {timeout})")
    print(f"{timeout}s {rpm}rpm = {steps} steps with MSTEP {mstep}, Speed {speed}")
    esp32.exec(f"mks.set_mstep({mstep})")
    time.sleep(0.1)

    out = lookup(esp32, "mks.read_pulses()")
    start_pulses = out.split(os.linesep)[-1]
    print("Start pulses:", start_pulses)

    assert start_pulses != 'None'

    out = lookup(esp32, f"mks.make_steps({steps}, speed={speed}, direction=1)")
    print(f"\n{out}")
    runtime = float(out.split(os.linesep)[-1])
    print(f"Controller return runtime {runtime}s")
    time.sleep(timeout + 2)

    out = lookup(esp32, "mks.read_pulses()")
    end_pulses = out.split(os.linesep)[-1]
    print("New pulses: ", end_pulses)
    assert end_pulses != 'None'

    assert timeout - 0.2 < runtime < timeout + 0.2
    assert int(start_pulses) + int(steps) == int(end_pulses)


@pytest.mark.parametrize("rpm", [5, 11.5, 55.5])
@pytest.mark.parametrize("timeout", [6.666, 9.999])
def test_mks_move_with_rpm(rpm_table, pyboard, rpm, timeout):
    print(f"\nRun motor {rpm}RPM for {timeout}s")
    esp32 = pyboard

    out = lookup(esp32, f"move_with_rpm(mks, {rpm}, {timeout}, rpm_table, direction=1)")
    print(out)
    runtime = out.split(os.linesep)[-1]
    print(f"Controller return runtime {runtime}s")
    time.sleep(timeout + 5)
    assert timeout - 0.2 < float(runtime) < timeout + 0.2


@pytest.mark.parametrize("rpm", np.arange(0.75, 200, 2))
def test_mks_ange_after_move_with_rpm(rpm_table, pyboard, rpm):
    esp32 = pyboard

    print(f"\nRun motor {rpm}RPM for half cycle")
    test_angle = 120
    timeout = 60 / rpm / (360 / test_angle)

    start_encoder = read_encoder(esp32)

    out = lookup(esp32, f"move_with_rpm(mks, {rpm}, {timeout}, rpm_table, direction=1)")
    print(out)
    runtime = out.split(os.linesep)[-1]
    print(f"Controller return runtime {runtime}s")
    time.sleep(timeout)

    end_encoder = read_encoder(esp32)
    relative_angle = abs(start_encoder - end_encoder) / 180
    print(f"Turn angle {relative_angle}°")

    assert timeout - 0.2 < float(runtime) < timeout + 0.2
    assert test_angle - 3 < relative_angle < test_angle + 3


def test_uart_buffer(rpm_table, pyboard):
    esp32 = pyboard
    esp32.exec("uart_buffer = UARTCommandBuffer()")
    esp32.exec('task = asyncio.create_task(uart_buffer.add_command(mks.read_pulses,'
               ' lambda response: print(f"Received response: {response}")))')

    out = lookup(esp32, "await task")
    print(out)


def test_mks_angle_stability(rpm_table, pyboard):
    esp32 = pyboard
    rpm = 8.8
    print(f"\nRun motor {rpm}RPM for half cycle {test_number} times")
    test_angle = 30
    timeout = 60 / rpm / (360 / test_angle)
    errors = []
    for i in range(1, test_number + 1):
        print("=" * 100)
        print(" " * 40, f"test No {i}")
        print("=" * 100)
        start_encoder = read_encoder(esp32)
        out = lookup(esp32, f"move_with_rpm(mks, {rpm}, {timeout / (rpm / 8)}, rpm_table, direction=1)")
        print(out)
        runtime = out.split(os.linesep)[-1]
        print(f"Controller return runtime {runtime}s")
        time.sleep(timeout + 0.1)

        end_encoder = read_encoder(esp32)
        relative_angle = abs(start_encoder - end_encoder) / 180
        print(f"Turn angle {relative_angle}°")

        angle_error = abs(relative_angle - test_angle)
        if angle_error > 8:
            print("-" * 20, f"\n\n\n\nERROR Angle: {abs(relative_angle - test_angle)}, Total Errors: {len(errors)}")
            print(f"Encoders values: {start_encoder}->{end_encoder}")
            errors.append(angle_error)
        if rpm < 10:
            rpm = 40
        else:
            rpm = 8
    for error in errors:
        print(error)
    assert len(errors) == 0


def test_mks_angle_stability_fixed_mstep(rpm_table, pyboard):
    esp32 = pyboard
    speed = 25

    print(f"\n50000 Steps with Mstep 100 {test_number} times")
    errors = []
    esp32.exec("mks.set_mstep(100)")
    for i in range(0, test_number):

        print("=" * 100)
        print(" " * 40, f"test No {i}, Errors: {len(errors)}")
        print("=" * 100)

        start_encoder = read_encoder(esp32)

        out = lookup(esp32, f"mks.make_steps(5000, {speed}, direction=1)")
        print(out)
        runtime = out.split(os.linesep)[-1]
        print(f"Controller return runtime {runtime}s")
        time.sleep(float(runtime) + 0.1)

        end_encoder = read_encoder(esp32)
        relative_angle = abs(start_encoder - end_encoder) / 180
        print(f"Turn angle {relative_angle}°")

        if speed <= 25:
            speed = 50
        else:
            speed = 25
        angle_error = abs(relative_angle - 90)
        if angle_error > 8:
            print("-" * 20, f"\n\n\n\nERROR: {angle_error}")
            errors.append(angle_error)
    assert len(errors) == 0
