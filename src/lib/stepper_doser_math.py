import os
from lib.exec_code import evaluate_expression
try:
    # Micropython Ulab
    from ulab import numpy as np
    from lib.servo42c import calc_steps
except:
    from lib.servo42c import calc_steps
    import numpy as np
    np.float = np.float32


MIN_MSTEP = 1
MSTEP_MAX = 253

SPEED_MIN = 1
SPEED_NUM = 127
STEPS_PER_REVOLUTION = 200

MAX_RPM = 1000
RPM_STEP = 0.125
RPM_TOLERANCE = 0.05

# Define the scale factor
SCALE_FACTOR = 2 ** 5


def file_or_dir_exists(filename):
    try:
        os.stat(filename)
        return True
    except OSError:
        return False


def calc_real_rpm(mstep, speed):
    if mstep == 0 or speed == 0:
        return 0
    return (speed * 30000) / (mstep * STEPS_PER_REVOLUTION)


# Generate buffer with RPM at MSTEP & Speed combinations
def make_rpm_table(regenerate=False, validate=False):
    print("Start generating rpm table")

    def crc8_8_atm(msg):
        crc = 0xFF
        for byte in msg:
            crc ^= byte
            for _ in range(8):
                crc = (crc << 1) ^ 0x07 if crc & 0x80 else crc << 1
            crc &= 0xff
        return crc ^ 0x00

    def validate_constants_checksum(filename="constants.crc"):
        if not file_or_dir_exists(filename):
            print(f"Missing files for {filename}")
            raise FileNotFoundError()
        with open(filename, "r") as read_file:
            stored_checksum = int(read_file.read())
        if stored_checksum != constants_checksum:
            print(f"crc mismach {stored_checksum}!={constants_checksum}")
            raise ValueError("Constants validation failed")

    def save_with_checksum(filename, array):
        np.save(filename, array)
        data = array.tobytes()
        checksum = crc8_8_atm(data)
        with open(f"{filename}.crc", "w") as write_file:
            write_file.write(str(checksum))

    def load_with_checksum(filename):
        # Check if the data file and its checksum file exist
        if not file_or_dir_exists(filename) or not file_or_dir_exists(f"{filename}.crc"):
            raise FileNotFoundError(f"Missing files for {filename}")

        array = np.load(filename)

        if validate:
            print(f"Validate {filename}.crc")
            # Load and validate checksum
            with open(f"{filename}.crc", "r") as read_file:
                stored_checksum = int(read_file.read())
            data = array.tobytes()
            checksum = crc8_8_atm(data)

            if checksum != stored_checksum:
                raise ValueError(f"Data validation failed for {filename}")

        return array

    def calc_rpm(motor_mstep, motor_speed):
        if motor_mstep == 0 and motor_speed == 0:
            return 0
        return (motor_speed * 30000) / (motor_mstep * STEPS_PER_REVOLUTION)

    constants_checksum = crc8_8_atm(
        "".join(map(str, [MIN_MSTEP, MSTEP_MAX, SPEED_MIN, SPEED_NUM, MAX_RPM, RPM_STEP])).encode())

    if not regenerate:
        try:
            print("Load constants check sum")
            validate_constants_checksum()
            print("Load closest_msteps.npy")
            closest_msteps = load_with_checksum('closest_msteps.npy')
            print("Load closest_speeds.npy")
            closest_speeds = load_with_checksum('closest_speeds.npy')
            print("Load closest_rpms.npy")
            closest_rpms = load_with_checksum('closest_rpms.npy')
            print("tables loaded from disk")
            return closest_rpms, closest_msteps, closest_speeds
        except Exception as e:
            print("Failed to load, calculate from sratch, ", e)
    files = ["closest_msteps.npy", "closest_msteps.npy.crc",
             "closest_speeds.npy", "closest_speeds.npy.crc",
             "closest_rpms.npy", "closest_rpms.npy.crc",
             "constants.crc"]
    for file in files:
        if file_or_dir_exists(file):
            os.remove(file)

    # Precompute RPM steps using NumPy for efficient calculations
    # Create a custom RPM steps array with varying resolutions
    rpm_steps = np.concatenate((
        np.arange(0, MAX_RPM // 250, RPM_STEP/2, dtype=np.float),
        np.arange(MAX_RPM // 250, MAX_RPM // 100, RPM_STEP, dtype=np.float),
        np.arange(MAX_RPM // 100, MAX_RPM // 10, RPM_STEP * 2, dtype=np.float),
        np.arange(MAX_RPM // 10, MAX_RPM // 4, RPM_STEP * 3, dtype=np.float),
        np.arange(MAX_RPM // 4, MAX_RPM, RPM_STEP * 4, dtype=np.float),
    ))

    # Initialize arrays to store the closest combinations
    closest_rpms = np.zeros(len(rpm_steps), dtype=np.float)
    closest_msteps = np.zeros(len(rpm_steps), dtype=np.uint8)
    closest_speeds = np.zeros(len(rpm_steps), dtype=np.uint8)
    for speed in range(SPEED_MIN, SPEED_NUM + 1):
        for mstep in range(MIN_MSTEP, MSTEP_MAX + 1):
            rpm = calc_rpm(mstep, speed)

            if rpm > MAX_RPM:
                continue

            # Find the nearest step index using NumPy operations for efficiency
            nearest_step_index = np.argmin(abs(rpm_steps - rpm))

            # Update if this combination is closer to the RPM step than the current closest
            if closest_rpms[nearest_step_index] == 0 or abs(rpm - rpm_steps[nearest_step_index]) < abs(
                    closest_rpms[nearest_step_index] - rpm_steps[nearest_step_index]):
                closest_rpms[nearest_step_index] = rpm
                closest_msteps[nearest_step_index] = mstep
                closest_speeds[nearest_step_index] = speed

    # Filter out steps that didn't have any combinations
    valid_indices = closest_rpms != 0
    closest_rpms = closest_rpms[valid_indices]
    closest_msteps = closest_msteps[valid_indices]
    closest_speeds = closest_speeds[valid_indices]

    save_with_checksum('closest_msteps.npy', closest_msteps)
    save_with_checksum('closest_speeds.npy', closest_speeds)
    save_with_checksum('closest_rpms.npy', closest_rpms)

    with open(f"constants.crc", "w") as f:
        f.write(str(constants_checksum))

    return closest_rpms, closest_msteps, closest_speeds


def find_combination(target_rpm, filtered_values):
    # Find the index of the closest RPM to the target RPM
    closest_index = np.argmin(abs(filtered_values[0] - target_rpm))
    return filtered_values[0][closest_index], filtered_values[1][closest_index], filtered_values[2][closest_index]


# Motor calibration points (RPM, flow rate in ml/min)
def extrapolate_flow_rate(calibration_points, degree=1):
    # Extracting RPM and flow rate values (RPM, flow rate in ml/min)
    rpm_values, flow_rate_values = zip(*calibration_points)
    # Fit a polynomial of degree
    if len(rpm_values) <= 2:
        degree = 1
    else:
        degree = min(degree, len(rpm_values)-2)
    print("degree= ", degree)
    print("max flow rate", max(flow_rate_values))
    print(f"Num RPM {len(rpm_values)}, NUM Flow: {len(flow_rate_values)}")
    coefficients = np.polyfit(rpm_values, flow_rate_values, degree)

    # Extrapolate flow rates for RPM values from 1 to max rpm
    extrapolated_rpm_values = np.arange(0, MAX_RPM + RPM_STEP, RPM_STEP*32)
    extrapolated_flow_rate_values = np.polyval(coefficients, extrapolated_rpm_values)
    extrapolated_flow_rate_values = np.maximum(extrapolated_flow_rate_values, 0)  # Set negative values to 0

    return extrapolated_rpm_values, extrapolated_flow_rate_values


def linear_interpolation(data):
    merged = []
    print(data)
    data.sort(key=lambda x: x[0])
    for i in range(len(data) - 1):
        x_start, y_start = data[i]
        x_end, y_end = data[i + 1]

        x_range = np.linspace(x_start, x_end, num=10)
        y_range = np.linspace(y_start, y_end, num=10)
        merged.extend(list(zip(x_range, y_range)))
    return merged


def move_with_rpm(mks, rpm, runtime, rpm_table, direction=0):
    rpm, mstep, speed = find_combination(rpm, rpm_table)
    steps = calc_steps(mks, rpm, mstep, runtime)

    if mks.set_mstep(mstep):
        return mks.make_steps(steps, speed=speed, direction=direction, stop=False)
    else:
        return False


def to_float(arr):
    if isinstance(arr, np.ndarray):
        # If it's a single-item NumPy array, extract the item and return
        return arr[0]
    else:
        return arr


async def stepper_run(mks, desired_rpm_rate, execution_time, direction, rpm_table, expression=False):
    print(f"Desired {to_float(desired_rpm_rate)}rpm, mstep")
    print("Limits expression: ", expression)
    if expression:
        result, logs = evaluate_expression(expression)
        if result:
            print(f"Limits check pass")
            calc_time = move_with_rpm(mks, desired_rpm_rate, execution_time, rpm_table, direction)
            return [calc_time]
    else:
        calc_time = move_with_rpm(mks, desired_rpm_rate, execution_time, rpm_table, direction)
        return [calc_time]
    print(f"Limits check not pass, skip dosing")
    return False
