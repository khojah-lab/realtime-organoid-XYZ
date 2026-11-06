"""Stand-in for adafruit_motorkit with inert steppers and DC motors."""


class _Stepper:
    def onestep(self, direction=None, style=None): pass
    def release(self): pass


class _DCMotor:
    throttle = 0.0


class MotorKit:
    def __init__(self, address=0x60):
        self.stepper1 = _Stepper()
        self.stepper2 = _Stepper()
        self.motor1 = _DCMotor()
        self.motor2 = _DCMotor()
        self.motor3 = _DCMotor()
        self.motor4 = _DCMotor()
