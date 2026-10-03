import RPi.GPIO as GPIO
import time

GPIO.setmode(GPIO.BOARD)

limit_switch = 11

GPIO.setup(limit_switch, GPIO.IN)

while True:
    if GPIO.input(limit_switch):
        print("HIGH")
    else:
        print("LOW")
    time.sleep(2)