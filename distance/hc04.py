# hc-sr04.py
"""MicroPython HC-SR04 distance measurement for ESP32-32D."""

import machine
import time

TRIG_PIN = 5
ECHO_PIN = 18

trig = machine.Pin(TRIG_PIN, machine.Pin.OUT)
echo = machine.Pin(ECHO_PIN, machine.Pin.IN)


def measure_distance_cm() -> float:
    trig.value(0)
    time.sleep_us(2)
    trig.value(1)
    time.sleep_us(10)
    trig.value(0)

    try:
        duration = machine.time_pulse_us(echo, 1, 30000)
    except OSError:
        return -1.0

    return duration * 0.0343 / 2.0
