#!/usr/bin/python3

# nohup sudo python3 server.py > output.log &
# ps ax | grep server.py
# sudo pkill -f server.py


#openssl req -x509 -newkey rsa:4096 -nodes -out cert.pem -keyout key.pem -days 365



from flask import Flask, render_template, request, Response, send_file
import eventlet
import socketio
import eventlet.wsgi
import os
import datetime
import base64
import copy
import PIL.Image as Image
import io
from threading import Thread
import pytz
from engineio.payload import Payload
from image_upload_script import *
from image_download_script import *
import smtplib
import cv2
import sys

Payload.max_decode_packets = 500


RPi_server_id = None

def convert_utc_to_local(ts):
	los_angeles_tz = pytz.timezone("America/Los_Angeles")
	ts = ts.replace(tzinfo=pytz.utc).astimezone(los_angeles_tz)
	return ts

global last_communcation_with_RPi
last_communcation_with_RPi = convert_utc_to_local(datetime.datetime.utcnow())

startTime = datetime.datetime.utcnow()
startTime = convert_utc_to_local(startTime)



sio = socketio.Server()#async_mode=async_mode)
app = Flask(__name__, static_url_path='', 
			static_folder='static',
			template_folder='templates')

app.wsgi_app = socketio.WSGIApp(sio, app.wsgi_app)


@app.route('/')
def index():
	return render_template('main.html')

@app.route('/update_parameters_motor', methods=['GET'])
def update_parameters_motor():
	motor_speed = float(request.args.get('motorspeed'))
	flow_dir = request.args.get('flow_dir')
	spin_dur = float(request.args.get('spin_dur'))
	data = {'motorspeed':motor_speed, 'flow_dir':flow_dir,'spin_dur':spin_dur}
	
	sio.emit('motor_parameters_update',{'data':data})

	return Response('Success')

# @app.route('/update_parameters_zoom_focus', methods=['GET'])
# def update_parameters_zoom_focus():
# 	focus_value = int(request.args.get('focus'))
# 	zoom_value = int(request.args.get('zoom'))
# 	data = {'focus':focus_value, 'zoom':zoom_value}
	
# 	sio.emit('camera_parameters_update',{'data':data})

# 	return Response('Success')


@app.route('/detect_organoid', methods=['GET'])
def detect_organoid():
	sio.emit('send_latest_image')
	return Response('Success')

@app.route('/retrieve_past_image', methods=['GET'])
def retrieve_past_image():
	image_timestamp = request.args.get('datetime')
	image_timestamp = datetime.datetime.strptime(image_timestamp, "%Y-%m-%dT%H:%M")

	if fetch_image(image_timestamp):
		path = "images_downloaded/" + image_timestamp.strftime("%d_%m_%Y_%H_%M") + '.png'
		data = base64.b64encode(open(path, 'rb').read()).decode('utf-8')
		sio.emit('response2',{'data':data})
	else:
		sio.emit('response2',{'data':False})

	return Response('Success')

# @app.route('/autofocus_camera_from_html', methods=['GET'])
# def autofocus_camera_from_html():
# 	sio.emit('autofocus_camera')
# 	return Response('Success')


@app.route('/get_system_parameters_from_html', methods=['GET'])
def get_system_parameters_from_html():
	sio.emit('get_system_parameters')
	return Response('Success')

@app.route('/prepare_download_images', methods=['GET'])
def prepare_download_images():
	from_datetimeval = request.args.get('from')
	from_datetimeval = datetime.datetime.strptime(from_datetimeval, "%Y-%m-%dT%H:%M")
	to_datetimeval = request.args.get('to')
	to_datetimeval = datetime.datetime.strptime(to_datetimeval, "%Y-%m-%dT%H:%M")

	fetch_images_from_t1_to_t2(from_datetimeval, to_datetimeval)
	return Response('Success')

@app.route('/download_images', methods = ['GET'])
def download_images():
	from_datetimeval = request.args.get('from')
	from_datetimeval = datetime.datetime.strptime(from_datetimeval, "%Y-%m-%dT%H:%M")
	to_datetimeval = request.args.get('to')
	to_datetimeval = datetime.datetime.strptime(to_datetimeval, "%Y-%m-%dT%H:%M")
	
	out_directory = 'images_downloaded/' + (from_datetimeval.strftime("%d_%m_%Y_%H_%M")) + '-' + (to_datetimeval.strftime("%d_%m_%Y_%H_%M")) 
	shutil.rmtree(out_directory)

	return send_file(out_directory + '.zip', as_attachment=True)	
	

@sio.event()
def pingpong(sid):
	sio.emit("send_data", room=sid)


@sio.event()
def latest_image(sid, data):
	sio.emit("receive_image_for_organoid_detection", data)
	
	
@sio.event()
def image_with_organoids(sid, data):
	print(data, file= sys.stderr)
	sio.emit('response3', {'data':data})

@sio.event()
def get_system_parameters_response(sid, data):
	sio.emit("system_parameters_to_html", {'data':data})



@sio.event
def connect(sid, data):
	global RPi_server_id
	if 'data' in data and data['data'] == "RPi":
		RPi_server_id = sid
	print("[INFO] Connect to the server")
	
	pingpong(sid)


@sio.event
def send(sid, data):
	global startTime
	current_time = datetime.datetime.now()
	current_time = convert_utc_to_local(current_time)
	global last_communcation_with_RPi
	last_communcation_with_RPi = current_time
	if startTime.minute != current_time.minute:

		path = 'images/' + str(current_time.month) + '/' + str(current_time.day) + '/' + str(current_time.hour) + '/'
		isExist = os.path.exists(path)
		if not isExist:
			os.makedirs(path)
		image_for_storing = copy.deepcopy(data)
		image_for_storing = image_for_storing.encode("utf-8")
		image_for_storing = base64.decodebytes(image_for_storing)
		
		image = Image.open(io.BytesIO(image_for_storing))
		image.save(path + '%s.png' % current_time.strftime("%d_%m_%Y_%H_%M"))
		startTime = current_time

	sio.emit('response',{'data':data})
	
@sio.event
def disconnect(sid):
	global RPi_server_id
	if sid == RPi_server_id:
		s = smtplib.SMTP('smtp.gmail.com', 587)
		s.starttls()
		s.login("emailalertraspberrypi@gmail.com", "sqro vjwh laaf qkef")
		message = "RaspberryPi Disconnected"
		s.sendmail("emailalertraspberrypi@gmail.com", "snpatil@ucsd.edu", message)
		s.quit()

	print("[INFO] disconnected from the server")

def check_raspberrpi_connection():
	global last_communcation_with_RPi
	while True:
		time.sleep(60)
		current_time = datetime.datetime.now()
		current_time = convert_utc_to_local(current_time) 
		if current_time - last_communcation_with_RPi > datetime.timedelta(minutes=3):
			s = smtplib.SMTP('smtp.gmail.com', 587)
			s.starttls()
			s.login("emailalertraspberrypi@gmail.com", "sqro vjwh laaf qkef")
			message = "RaspberryPi Disconnected"
			s.sendmail("emailalertraspberrypi@gmail.com", "snpatil@ucsd.edu", message)
			s.quit()
			break

@sio.event
def image_store_upload(sid):
	thread = Thread(target=set_upload_time)
	thread.start()
	thread2 = Thread(target=check_raspberrpi_connection)
	thread2.start()
	return 'started'


if __name__ == '__main__':
	certificate = '../certificate/ssl-bundle.crt'
	key = '../certificate/organoid.key'
	
	eventlet.wsgi.server(eventlet.wrap_ssl(eventlet.listen(('0.0.0.0', 443)),
						  certfile=certificate,
						  keyfile=key,
						  server_side=True), app)
