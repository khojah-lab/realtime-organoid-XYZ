import cv2
import pickle


distorted_img_filename = "07_08_2023_19_07.png"
distorted_image = cv2.imread(distorted_img_filename)



calib_result_pickle = pickle.load(open("camera_calib_pickle.p", "rb" ))
mtx = calib_result_pickle["mtx"]
optimal_camera_matrix = calib_result_pickle["optimal_camera_matrix"]
dist = calib_result_pickle["dist"]


undistorted_image = cv2.undistort(distorted_image, mtx, dist, None, 
                                    optimal_camera_matrix)
size = len(distorted_img_filename)
new_filename = distorted_img_filename[:size - 4]
new_filename = new_filename + '_undistorted.jpg'
    
# Save the undistorted image
cv2.imwrite(new_filename, undistorted_image)