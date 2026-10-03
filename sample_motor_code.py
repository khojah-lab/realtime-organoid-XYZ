from adafruit_motorkit import MotorKit
from adafruit_motor import stepper
import RPi.GPIO as GPIO
import keyboard

kit2 = MotorKit(address=0x61)


while True:
	if keyboard.is_pressed('up'):
		kit2.stepper2.onestep(direction=stepper.FORWARD)
	elif keyboard.is_pressed('down'):
		kit2.stepper2.onestep(direction=stepper.BACKWARD)
	elif keyboard.is_pressed('left'):
		kit2.stepper1.onestep(direction=stepper.BACKWARD)
	elif keyboard.is_pressed('right'):
		kit2.stepper1.onestep(direction=stepper.FORWARD)
	elif keyboard.is_pressed('q'):
		break
	kit2.stepper1.release()
	kit2.stepper2.release()
