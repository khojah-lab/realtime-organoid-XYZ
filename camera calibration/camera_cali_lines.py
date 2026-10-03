import cv2 # Import the OpenCV library to enable computer vision
import numpy as np # Import the NumPy scientific computing library
 
filename = '07_08_2023_20_23.png'
 
# Chessboard dimensions
number_of_squares_X = 7 # Number of chessboard squares along the x-axis
number_of_squares_Y = 10  # Number of chessboard squares along the y-axis
nX = number_of_squares_X - 1 # Number of interior corners along x-axis
nY = number_of_squares_Y - 1 # Number of interior corners along y-axis
 
def main():
     
  # Load an image
  image = cv2.imread(filename)
 
  # Convert the image to grayscale
  gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)  
 
  # Find the corners on the chessboard
  success, corners = cv2.findChessboardCorners(gray, (nY, nX), None)
     
  # If the corners are found by the algorithm, draw them
  if success == True:
 
    # Draw the corners
    cv2.drawChessboardCorners(image, (nY, nX), corners, success)
 
    # Create the output file name by removing the '.jpg' part
    size = len(filename)
    new_filename = filename[:size - 4]
    new_filename = new_filename + '_drawn_corners.png'     
     
    # Save the new image in the working directory
    cv2.imwrite(new_filename, image)
 
    # Display the image 
    # cv2.imshow("Image", image) 
     
    # Display the window until any key is pressed
    # cv2.waitKey(0) 
     
    # Close all windows
    # cv2.destroyAllWindows() 
     
main()