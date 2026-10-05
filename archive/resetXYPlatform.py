from adafruit_motorkit import MotorKit
from adafruit_motor import stepper
import RPi.GPIO as GPIO
import keyboard
import time

# GPIO.setmode(GPIO.BOARD)
limit_switch_lr = 17
limit_switch_ud = 27

GPIO.setup(limit_switch_lr, GPIO.IN)
GPIO.setup(limit_switch_ud, GPIO.IN)


# Initialise the first hat on the default address
# kit1 = MotorKit()
# Initialise the second hat on a different address
kit2 = MotorKit(address=0x61)



while GPIO.input(limit_switch_ud):
	kit2.stepper2.onestep(direction=stepper.BACKWARD)
	kit2.stepper2.release()
	# time.sleep(0.5)

while GPIO.input(limit_switch_lr):
	kit2.stepper1.onestep(direction=stepper.FORWARD)
	kit2.stepper1.release()
	# time.sleep(0.5)
	




