def check_defaults_calibration(calibration_points, max_pumps):
    for p in range(1, max_pumps + 1):
        pump_key = f"calibrationDataPump{p}"
        if pump_key not in calibration_points:
            calibration_points[pump_key] = [
                {"rpm": 100, "flowRate": 100},
                {"rpm": 500, "flowRate": 400},
                {"rpm": 1000, "flowRate": 800}
            ]


def check_defaults_settings(settings):
    if "pump_number" not in settings:
        settings["pump_number"] = 9
    if "hostname" not in settings:
        settings["hostname"] = "doser"
    if "timezone" not in settings:
        settings["timezone"] = 0.0
    if "timeformat" not in settings:
        settings["timeformat"] = 0
    if "ntphost" not in settings:
        settings["ntphost"] = "time.google.com"
    if "analog_period" not in settings:
        settings["analog_period"] = 60
    if "pumps_current" not in settings:
        settings["pumps_current"] = [1000] * 9
    if "inversion" not in settings:
        settings["inversion"] = [0] * 9
    if "names" not in settings:
        settings["names"] = [f"Pump {i+1}" for i in range(9)]
    if "color" not in settings:
        settings["color"] = "dark"
    if "theme" not in settings:
        settings["theme"] = "cerulean"
    if "whatsapp_number" not in settings:
        settings["whatsapp_number"] = ""
    if "whatsapp_apikey" not in settings:
        settings["whatsapp_apikey"] = ""
    if "telegram" not in settings:
        settings["telegram"] = ""


def check_defaults_storage(storage, max_pumps):
    for p in range(1, max_pumps + 1):
        if f"pump{p}" not in storage:
            storage[f"pump{p}"] = 0
        if f"remaining{p}" not in storage:
            storage[f"remaining{p}"] = 0


def check_defaults_analog_settings(analog_settings, max_pumps):
    for p in range(1, max_pumps + 1):
        pump_key = f"pump{p}"
        if pump_key not in analog_settings:
            analog_settings[pump_key] = {
                "enable": False,
                "pin": 99,
                "dir": 1,
                "points": [
                    {"analogInput": 0, "flowRate": 0},
                    {"analogInput": 100, "flowRate": 5}
                ]
            }
        else:
            # Ensuring all nested settings are complete
            if "enable" not in analog_settings[pump_key]:
                analog_settings[pump_key]["enable"] = False
            if "pin" not in analog_settings[pump_key]:
                analog_settings[pump_key]["pin"] = 99
            if "dir" not in analog_settings[pump_key]:
                analog_settings[pump_key]["dir"] = 1
            if "points" not in analog_settings[pump_key]:
                analog_settings[pump_key]["points"] = [
                    {"analogInput": 0, "flowRate": 0},
                    {"analogInput": 100, "flowRate": 5}
                ]


def check_defaults_schedule(schedule, max_pumps):
    for p in range(1, max_pumps + 1):
        pump_key = f"pump{p}"
        if pump_key not in schedule:
            schedule[pump_key] = []


def check_defaults_mqtt(mqtt_settings):
    if "broker" not in mqtt_settings:
        mqtt_settings["broker"] = ""
    if "login" not in mqtt_settings:
        mqtt_settings["login"] = ""
    if "password" not in mqtt_settings:
        mqtt_settings["password"] = ""


def check_defaults_limits(limits, max_pumps):
    for p in range(1, max_pumps + 1):
        key = str(p)
        if key not in limits:
            limits[key] = "True"
