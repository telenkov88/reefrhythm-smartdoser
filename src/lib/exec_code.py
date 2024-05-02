import io
import sys


sensetive_keys = ['time', 'os', 'sys', 'Microdot', 'redirect', 'send_file', 'with_sse', 're', 'requests', 'mcron',
                  'json', 'calc_steps', 'np', 'file_or_dir_exists', 'calc_real_rpm', 'make_rpm_table',
                  'find_combination', 'extrapolate_flow_rate', 'linear_interpolation', 'move_with_rpm', 'stepper_run',
                  'struct', 'calc_crc', 'Servo42c', 'asyncio', 'CustomFuture', 'CommandBuffer', 'TaskManager',
                  'analog_pins', 'gc', 'Mock', 'MagicMock', 'mac_address', 'network', 'wifi', 'ADC', 'Pin', 'ntptime',
                  'unique_id', 'mock_adc', 'ubinascii', 'utime', 'random_adc_read', 'uart', 'ota', 'machine',
                  'web_compress', 'web_file_extension', 'get_points', 'get_analog_settings', 'get_time',
                  'calibration_points', 'read_file', 'analog_settings', 'settings', 'schedule', 'mks_dict',
                  'mqtt_login', 'mqtt_password', 'chart_points', 'cal_points', 'new_rpm_values', 'new_flow_rate_values',
                  'analog_chart_points', 'analog_en', 'analog_pin', 'analog_points', 'command_buffer',
                  'load_files_to_ram', 'evaluate_expression', 'get_filtered_vars', 'addon', 'binascii',
                  'mqtt_client', 'RELEASE_TAG', 'USE_RAM', 'html_files', 'filenames', 'js_files', 'file', 'css_files',
                  'app', 'ota_lock', 'ota_progress', 'firmware_size', 'should_continue', 'c', 'mcron_keys',
                  'time_synced', 'byte_string', 'hex_string', 'download_file_async', 'to_float',
                  'analog_control_worker', 'start_timer', 'end_timer', 'get_rpm_points', 'get_flow_points',
                  'get_analog_chart_points', 'get_free_mem', 'favicon', 'manifest', 'styles', 'javascript', 'static',
                  'run_with_rpm', 'dose', 'index', 'dose_ssetime', 'dose_sse', 'ota_events', 'ota_upgrade',
                  'calibration', 'setting_responce', 'setting_process_post', 'update_schedule', 'sync_time',
                  'update_sched_onstart', 'maintain_memory', 'mqtt_worker', 'mqtt_dose_buffer', 'mqtt_run_buffer',
                  'process_mqtt_cmd', 'main', 'start_web_server', 'wifi_config', 'wifi_settings', 'password',
                  'rpm_table', 'time']


def get_filtered_vars(global_vars, keys):
    return {k: v for k, v in global_vars.items() if k not in keys and not k.startswith('__')}


def evaluate_expression(expression, allowed_vars={}):
    # Remove unwanted modules from allowed_vars
    allowed_vars = {key: val for key, val in allowed_vars.items() if key not in sensetive_keys}  # Explicitly blocking some modules
    #print(allowed_vars.keys())
    log_capture_string = io.StringIO()
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = log_capture_string
    sys.stderr = log_capture_string

    result = None
    try:
        # Evaluate the expression safely with limited scope
        result = eval(expression, {"__builtins__": None}, allowed_vars)
    except Exception as e:
        print(f"Error evaluating expression: {e}")
    finally:
        # Restore stdout and stderr to their original states
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    # Get all logged output
    logs = log_capture_string.getvalue()
    log_capture_string.close()

    return result, logs


class ProtectedNamespace(dict):
    def __init__(self, global_vars, local_vars):
        super().__init__()
        self.global_vars = global_vars  # This holds read-only global variables
        self.local_vars = local_vars  # Local variables that can be modified

    def __getitem__(self, key):
        if key in self.local_vars:
            return self.local_vars[key]
        if key in self.global_vars:
            return self.global_vars[key]
        raise KeyError(f"{key} not found in either local or global scope.")

    def __setitem__(self, key, value):
        if key in self.global_vars:
            raise RuntimeError("Cannot modify global variables")
        self.local_vars[key] = value


def execute_code_with_protection(code, local_vars=None):
    # Fetch all global variables from the caller's environment automatically
    global_vars = globals()

    if local_vars is None:
        local_vars = {}

    # Create a StringIO object to capture output
    log_capture_string = io.StringIO()
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = log_capture_string
    sys.stderr = log_capture_string

    # Namespace setup
    namespace = ProtectedNamespace(global_vars, local_vars)

    try:
        # Execute code within the protected namespace
        exec(code, {}, namespace)
        execution_result = True
    except Exception as e:
        print(f"Error: {e}")
        execution_result = False

    # Restore stdout and stderr
    sys.stdout = old_stdout
    sys.stderr = old_stderr

    # Get the log output
    logs = log_capture_string.getvalue()
    log_capture_string.close()

    return execution_result, logs


if __name__ == '__main__':
    x = 10
    code = f"""
# Local variables can be defined:
local_var = 123
print("local variable =", local_var)
# Read only access to global variable
print("Global var x = ",x)
# Modification of global var are not allowed:
x= 123
"""

    result, logs = execute_code_with_protection(code)
    print("Execution result:", result)
    print("Logs:\n", logs)
