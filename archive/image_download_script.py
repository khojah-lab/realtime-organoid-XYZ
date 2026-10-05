from swiftCloudAuth import *
import datetime
import os
from prepare_zip import *

def getPathfromTimestamp(ts):
	return 'images/' + str(ts.month) + '/' + str(ts.day) + '/' + str(ts.hour) + '/' + ts.strftime("%d_%m_%Y_%H_%M") + '.png'

def getPrefix(ts):
	return 'images/' + str(ts.month) + '/' + str(ts.day) + '/' + str(ts.hour) + '/'

def fetch_image(timeStamp):
	basePath = 'images_downloaded/'
	isExist = os.path.exists(basePath)
	if not isExist:
		os.makedirs(basePath)
	
	x = sv.download('image_store_motor', objects=[getPathfromTimestamp(timeStamp)], options={'out_directory': 'images_downloaded/', 'prefix': getPrefix(timeStamp), 'remove_prefix':True})
	for t in x:
		return t['success']


def fetch_images_from_t1_to_t2(t1, t2):

	basePath = 'images_downloaded/'
	isExist = os.path.exists(basePath)
	if not isExist:
		os.makedirs(basePath)
		
	out_directory = 'images_downloaded/' + (t1.strftime("%d_%m_%Y_%H_%M")) + '-' + (t2.strftime("%d_%m_%Y_%H_%M")) + '/'
	
	t1 = t1.replace(second=59)
	t2 = t2.replace(second=59)
	
	while t1 <= t2:
		t1_end_of_hour = t1.replace(minute=59)
		files = []

		while t1 <= t1_end_of_hour and t1 <= t2:	
			files.append(getPathfromTimestamp(t1))
			t1 = t1 + datetime.timedelta(minutes = 1)

		x = sv.download('image_store_motor', objects=files, options={'out_directory': out_directory, 'prefix': getPrefix(t1_end_of_hour), 'remove_prefix':True})
		for _ in x:
			pass
	
	write_zip_file(out_directory)
	return out_directory[:-1] + '.zip'



# fetch_image(datetime.datetime.now() - datetime.timedelta(days=4))
