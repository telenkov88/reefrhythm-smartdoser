import array
import random
try:
    import micropython
    from ulab import numpy as np
except ImportError:
    from lib.mocks import micropython, ptr8, ptr16, ptr32
    import numpy as np

from lib.decorator import timed_function

TEST_CYCLES = 10000


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
    for _count in range(cycles):
        total = int(0)
        for i in range(length):
            total += int(ptr_arr[i])  # Explicit conversion to ensure correct type handling
    return total


@timed_function
def avg_float_array(arr: array, length: int, cycles: int) -> float:
    _sum: float = 0.0
    for _count in range(cycles):
        _sum: float = 0.0
        for _ in range(length):
            _sum += arr[_]
    return _sum / length if length > 0 else 0.0


@micropython.native
@timed_function
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

BUFFER_SIZE = 100
buffer = array.array('H', [0]*BUFFER_SIZE)


for _ in range(BUFFER_SIZE):
    buffer[_] = 65535
print(buffer)
print("\r\nPython emitter")
s1 = sum_int16_array(buffer, BUFFER_SIZE, TEST_CYCLES)
print("\r\nNative emitter")
s2 = sum_int16_array_native(buffer, BUFFER_SIZE, TEST_CYCLES)
print("\r\nViper emitter")
s3 = sum_int16_array_viper(buffer, BUFFER_SIZE, TEST_CYCLES)

if not (s1 == s2 == s3):
    raise ValueError(f"Array summ not equal: {s1}, {s2}, {s3}")
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
@micropython.native
def avg_numpy_for_float(arr, cycles: int) -> float:
    _avg: float = 0.0
    for _count in range(cycles):
        _avg = np.mean(arr)
    return _avg

@timed_function
@micropython.native
def avg_numpy_for_float_optimized(arr, cycles: int) -> float:
    _avg: float = 0.0
    for _count in range(cycles):
        _avg = np.mean(arr)/10000
    return float(_avg)


print("\r\nViper optimized float emitter:")
a3 = avg_viper_for_float(buffer_float_to_int, BUFFER_SIZE, TEST_CYCLES)

print("\r\nNumpy float array calculation:")
a4 = avg_numpy_for_float(np_array, TEST_CYCLES)

print("\r\nNumpy float optimized array calculation:")
a5 = avg_numpy_for_float_optimized(np_array_optimized, TEST_CYCLES)


tolerance = 0.001  # Float error tolerance level
if not (abs(a1 - a2) < tolerance and abs(a2 - a3) < tolerance and abs(a3 - a4) < tolerance and abs(a4 - a5) < tolerance):
    values = f"{round(a1, 3)}, {round(a2, 3)}, {round(a3, 3)}, {round(a4, 3)}, {round(a5, 3)}"
    raise ValueError(f"Array average value not equal: ", values)
else:
    print("Array avg: ", a4)
