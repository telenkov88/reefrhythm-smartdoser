import array
import random
import sys

try:
    import micropython
    from ulab import numpy as np
except ImportError:
    from lib.mocks import micropython, ptr8, ptr16, ptr32, uint
    import numpy as np

from lib.decorator import timed_function

TEST_CYCLES = 10000
BUFFER_SIZE = 100


@timed_function
def sum_int16_array(arr: array, length: int, cycles: int) -> int:
    total = int(0)
    for _count in range(cycles):
        total = int(0)
        for _ in range(length):
            total += arr[_]
    return total


@timed_function
@micropython.native
def sum_int16_array_native(arr: array, length: int, cycles: int) -> int:
    total = int(0)
    for _count in range(cycles):
        total = int(0)
        for _ in range(length):
            total += arr[_]
    return total


@timed_function
@micropython.viper
def sum_int16_array_viper(arr: ptr16, length: int, cycles: int) -> int:
    total = int(0)
    ptr_arr = ptr16(arr)  # Explicit pointer type to ensure correct handling
    c = int(0)
    while c < cycles:
        total = int(0)
        k = int(0)
        while k < length:
            total += int(ptr_arr[k])  # Explicit conversion to ensure correct type handling
            k += 1
        c += 1
    return total


@timed_function
@micropython.viper
def sum_int16_array_viper_direct_pointer(arr: ptr16, l: uint, cycles: uint) -> int:
    initial_ptr = uint(arr)  # Store the initial pointer
    c = uint(0)
    r: int = 0  # Reset r for each cycle
    while c < cycles:
        r:int = 0  # Reset r for each cycle
        p = ptr16(initial_ptr)  # Reset p to the start of the array for each cycle
        pstop: uint = uint(p) + 2 * l  # Calculate the end pointer
        while uint(p) < pstop:
            r += p[0]  # Dereference the current pointer location
            p = ptr16(uint(p) + 2)  # Increment pointer by the size of int16 (2 bytes)
        c += 1
    print("viper sum", r)
    return r


@timed_function
def sum_int16_array_numpy(arr, cycles: int) -> int:
    total = int(0)
    for _count in range(cycles):
        total = int(np.sum(arr))
    return total

# =========================== Floats ======================================
@timed_function
def avg_float_array(arr: array, length: int, cycles: int) -> float:
    _sum: float = 0.0
    for _count in range(cycles):
        _sum: float = 0.0
        for _ in range(length):
            _sum += arr[_]
    return _sum / length if length > 0 else 0.0


@timed_function
@micropython.native
def avg_float_array_native(arr: array, length: int, cycles: int) -> float:
    _sum: float = 0.0
    for _count in range(cycles):
        _sum: float = 0.0
        for _ in range(length):
            _sum += arr[_]
    return _sum / length if length > 0 else 0.0


print('\r\n', "="*50)
print("Test Int16 array summ performance")
print("="*50)


buffer = array.array('H', [0]*BUFFER_SIZE)


for _ in range(BUFFER_SIZE):
    buffer[_] = random.randint(0, 65535)

np_int_array = np.array(buffer)
print(buffer)
print("\r\nPython emitter")
s1 = sum_int16_array(buffer, BUFFER_SIZE, TEST_CYCLES)
print("\r\nNative emitter")
s2 = sum_int16_array_native(buffer, BUFFER_SIZE, TEST_CYCLES)
print("\r\nViper emitter")
s3 = sum_int16_array_viper(buffer, BUFFER_SIZE, TEST_CYCLES)

print("\r\nNumpy emitter")
s4 = sum_int16_array_numpy(np_int_array, TEST_CYCLES)
tolerance = 2  # Allow a difference of 1 unit in the sum

if sys.implementation.name == "micropython":
    print("\r\nViper emitter with direct pointer")
    s_direct = sum_int16_array_viper_direct_pointer(buffer, BUFFER_SIZE, TEST_CYCLES)
    if not (abs(s1 - s_direct) == 0):
        values = f"{s1}, {s4}"
        raise ValueError(f"Array summation not equal: {values}")

if not (abs(s1 - s2) == 0 and abs(s2 - s3) == 0 and abs(s3 - s3) == 0 and abs(s1 - s4) <= tolerance):
    values = f"{s1}, {s2}, {s3}, {s4}, {s4}"
    raise ValueError(f"Array summation not equal: {values}")
else:
    print("Array sum: ", s1)


print('\r\n', "="*50)
print("| Test float array summ and avg calc performance |")
print("="*50)

buffer = array.array('f', [0]*BUFFER_SIZE)
buffer_float_to_int = array.array('H', [0]*BUFFER_SIZE)

for _ in range(BUFFER_SIZE):
    value = random.uniform(0.0, 3.3)
    buffer[_] = value
    buffer_float_to_int[_] = int(value * 10000)
np_array = np.array(buffer)
np_array_optimized = np.array(buffer_float_to_int)

print(buffer)
print("\r\nPython emitter")
a1 = avg_float_array_native(buffer, BUFFER_SIZE, TEST_CYCLES)
print("\r\nNative emitter")
a2 = avg_float_array_native(buffer, BUFFER_SIZE, TEST_CYCLES)

# Viper doesn't support float, but we can use store float values as int and then calculate floats in native
@timed_function
def avg_viper_for_float(arr: array, length: int, cycles: int) -> float:
    _sum = sum_int16_array_viper(arr, BUFFER_SIZE, cycles)
    _avg: float = 0.0
    for _count in range(cycles):
        _avg: float = 0.0
        _avg = _sum / length if length > 0 else 0.0
    return _avg/10000

@timed_function
def avg_viper_for_float_direct_pointer(arr: array, length: int, cycles: int) -> float:
    _sum = sum_int16_array_viper_direct_pointer(arr, BUFFER_SIZE, cycles)
    _avg: float = 0.0
    for _count in range(cycles):
        _avg: float = 0.0
        _avg = _sum / length if length > 0 else 0.0
    return _avg/10000

@timed_function
@micropython.native
def avg_numpy_for_float(arr, cycles: int) -> float:
    _avg: float = 0.0
    for _count in range(cycles):
        _avg = np.mean(arr)
    return _avg


print("\r\nViper optimized float emitter:")
a3 = avg_viper_for_float(buffer_float_to_int, BUFFER_SIZE, TEST_CYCLES)

print("\r\nNumpy float array calculation:")
a4 = avg_numpy_for_float(np_array, TEST_CYCLES)


tolerance = 0.001  # Float error tolerance level
if not (abs(a1 - a2) < tolerance and abs(a2 - a3) < tolerance and abs(a3 - a4) < tolerance):
    values = f"{round(a1, 3)}, {round(a2, 3)}, {round(a3, 3)}, {round(a4, 3)}"
    raise ValueError(f"Array average value not equal: ", values)
else:
    print("Array avg: ", a4)

if sys.implementation.name == "micropython":
    print("\r\nViper optimized float emitter with direct pointer")
    a_direct = avg_viper_for_float_direct_pointer(buffer_float_to_int, BUFFER_SIZE, TEST_CYCLES)
    if not (abs(a1 - a_direct) < tolerance):
        values = f"{round(a1, 3)}, {round(a_direct, 3)}"
        raise ValueError(f"Array summation not equal: {values}")
