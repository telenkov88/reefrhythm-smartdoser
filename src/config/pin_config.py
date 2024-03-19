
try:
    from machine import UART, Pin
    en_pin = Pin(12, mode=Pin.OUT, value=1)
    tx_pin = 43
    rx_pin = 44
except ImportError:
    print("local debugging")


