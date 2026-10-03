#Modified by smartbuilds.io
#Date: 27.09.20
#Desc: This web application serves a motion JPEG stream
# main.py
# import the necessary packages
from flask import Flask, render_template, Response, request

import os
from FocuserExample import *



camera = Camera()
camera.start_preview()
focuser = Focuser(bus = 1)
# auto_focus = AutoFocus(focuser,camera)
auto_focus = None

import time
import board
from adafruit_motorkit import MotorKit

kit = MotorKit(i2c=board.I2C())

# App Globals (do not edit)
app = Flask(__name__)

@app.route('/')
def index():
    return render_template('main.html') #you can customze index.html here

def gen(camera):
    #get camera frame
    while True:
        frame = camera.getByteFrame()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(gen(camera),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

def change_motor_speed_direction(speed, direction):
    if direction == "UP":
        kit.motor1.throttle = -speed
        kit.motor2.throttle = +speed
        kit.motor3.throttle = +speed
        kit.motor4.throttle = -speed
    elif direction == "DOWN":
        kit.motor1.throttle = +speed
        kit.motor2.throttle = -speed
        kit.motor3.throttle = -speed
        kit.motor4.throttle = +speed
    elif direction == "RIGHT":
        kit.motor1.throttle = +speed
        kit.motor2.throttle = +speed
        kit.motor3.throttle = -speed
        kit.motor4.throttle = -speed
    elif direction == "LEFT":
        kit.motor1.throttle = -speed
        kit.motor2.throttle = -speed
        kit.motor3.throttle = +speed
        kit.motor4.throttle = +speed
    time.sleep(0.05)
    kit.motor1.throttle = 0
    kit.motor2.throttle = 0
    kit.motor3.throttle = 0
    kit.motor4.throttle = 0
    

@app.route('/update_parameters', methods=['GET'])
def update_parameters():
    focus_value = int(request.args.get('focus'))
    zoom_value = int(request.args.get('zoom'))
    motor_speed = float(request.args.get('motorspeed'))
    motor_dir = request.args.get('motordir')

    global image_count
    change_motor_speed_direction(motor_speed, motor_dir)

    focuser.set(Focuser.OPT_FOCUS, focus_value)
    focuser.set(Focuser.OPT_ZOOM, zoom_value)
    return Response('Success')
    


# # Take a photo when pressing camera button
# @app.route('/picture')
# def take_picture():
#     pi_camera.take_picture()
#     return "None"

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=False)    
    camera.stop_preview()
    camera.close()