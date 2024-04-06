try:
    from machine import UART, Pin

    tx_pin = 43
    rx_pin = 44
except ImportError:
    print("local debugging")

analog_pins = [5, 6, 7, 15, 16, 17, 18, 8, 3]  # Allowed ADC pins for pumps control
