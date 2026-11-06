"""Stand-in for RPi.GPIO: records nothing, reads every pin as low."""
BCM = "BCM"
IN = "IN"
OUT = "OUT"
HIGH = 1
LOW = 0


def setmode(mode): pass
def setup(pin, direction): pass
def output(pin, value): pass
def input(pin): return LOW
def cleanup(): pass
