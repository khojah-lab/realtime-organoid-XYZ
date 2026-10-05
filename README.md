This GitHub contains code for the XYZ device. 

Organoids, used in regenerative medicine research and tissue engineering, are miniature tissue models derived from stem cells that mimic structure, function, and cellular complexity of human organs in vitro. Due to their similar properties to organs, organoids have become a major focus in biomedical research, aiding in understanding of tissue engineering, regenerative medicine, and organ regrowth potential. However, organoids are extremely sensitive to their environment, making research reproducibility difficult; thus, organoids require frequent monitoring and delicate care to thrive. Non-invasive, live imaging is crucial for monitoring growth, morphological changes, organoid health, and movement.

In previous years, UCSD researchers in Reem Khojah’s lab have designed a custom device tackling this research problem. 

XYZ is an organoid imaging device utilizing Raspberry Pi, Python, stepper and suspended motors, and 3-D printed hardware parts. The web browser is an interface allowing for remote control of the XYZ device, written in HTML. The web browser allows for lab users to control settings such as camera position and suspended motor usage.

Main aspects of the web browser include: 
- Live feed, which allows users to see how the organoids look in the lab at any given moment
- Automated scan, which takes a picture of the center of each well in a 6-well plate recurringly. It runs by counting a number of steps to take in each direction, and then pauses to take a still image. Mathmatically, it returns to the home spot (bottom right). Images are saved to an images folder.
- Action log, which records previous actions done. It has a local display on the web browser (in which the actions reset after refreshing the browser), but all actions are also saved to actions.csv. This was made to improve the reproducibility of organoid research, in which events can be traced back to an action with a date and time. 

To run RPi web browser locally: cd into SpringXYZ folder, activate venv, and run server.py: 

- cd SpringXYZ
- source venv/bin/activate
- python3 server.py

To edit: nano server.py
