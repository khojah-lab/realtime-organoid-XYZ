from flask import Flask, render_template, Response, request, send_file, jsonify
from flask_socketio import SocketIO
from picamera2 import Picamera2
import cv2
import time
import threading
import datetime
import os
import base64
import pytz
from timing import Timer, log_event, set_socketio

# =========================
# MOTOR + GPIO IMPORTS
# =========================
from motor_control import (
    move_up, move_down, move_left, move_right,
    move_forward, move_backward, release_all,
    x_motor, y_motor,                          # shared kit2 steppers — no second MotorKit at 0x61
)
from dc_motor_control import (
    set_motor, set_all_motors, stop_all_motors, get_motor_states,
    stop_motor as stop_motor_single,
)
from adafruit_motor import stepper
import RPi.GPIO as GPIO

# =========================
# GPIO SETUP (limit switches)
# =========================
GPIO.setmode(GPIO.BCM)
LIMIT_SWITCH_LR = 17
LIMIT_SWITCH_UD = 27
GPIO.setup(LIMIT_SWITCH_LR, GPIO.IN)
GPIO.setup(LIMIT_SWITCH_UD, GPIO.IN)

# =======================
# LED Setup
# ======================
LED_PIN = 18
GPIO.setup(LED_PIN, GPIO.OUT)
GPIO.output(LED_PIN, GPIO.LOW)
led_state = False

# =========================
# FLASK + SOCKET.IO
# =========================
app = Flask(__name__, template_folder='templates')
app.config['SECRET_KEY'] = 'microscopy_secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
set_socketio(socketio)

# =========================
# CAMERA SETUP
# picam2 is started once and never stopped.
# =========================
picam2 = Picamera2()

camera_config = picam2.create_video_configuration(
    main={"size": (1024, 1024)},   # high-quality capture stream
    lores={"size": (800, 800)},   # smooth web preview stream
    display="lores",
    buffer_count=6
)

picam2.configure(camera_config)


picam2.start()
time.sleep(2)


# =========================
# SYSTEM PARAMETERS
# =========================
system_params = {
    "zoom":           0,
    "focus":          0,
    "motor_speed":    0,
    "flow_direction": "OFF",
    "spin_duration":  0,
}

# =========================
# SCAN STATUS (shown in UI)
# =========================
scan_status = {
    "running":       False,
    "last_scan":     "Never",
    "next_scan":     "Calculating...",
    "current_step":  "",
}

# =========================
# SHARED FRAME BUFFER
# =========================
latest_frame = None
frame_lock   = threading.Lock()
camera_lock  = threading.Lock()


def capture_loop():
    global latest_frame

    while True:
        try:
            with camera_lock:
                request = picam2.capture_request()

                frame = request.make_array("main")

                request.release()

            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            with frame_lock:
                latest_frame = frame

        except Exception as e:
            print(f"Capture error: {e}")

        time.sleep(0.033)

threading.Thread(target=capture_loop, daemon=True).start()


# =========================
# MJPEG LIVE STREAM
# =========================
def generate_frames():
    while True:
        # 1. Lock the thread, safely copy the frame, then immediately release the lock
        with frame_lock:
            if latest_frame is None:
                frame_to_encode = None
            else:
                # Making a deep copy prevents the capture thread from modifying this data
                frame_to_encode = latest_frame.copy()

        # If the camera hasn't initialized a frame yet, wait slightly and skip
        if frame_to_encode is None:
            time.sleep(0.01)
            continue

        try:
            # 2. Perform the heavy JPEG encoding OUTSIDE of the lock area
            # This keeps your stream fluid and prevents blocking the camera hardware
            ret, buffer = cv2.imencode('.jpg', frame_to_encode, [cv2.IMWRITE_JPEG_QUALITY, 80])
            
            if not ret:
                continue
                
            frame_bytes = buffer.tobytes()
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                   
        except Exception as e:
            print(f"Streaming encoding error: {e}")
            time.sleep(0.05)

        # 3. Throttle the loop slightly to match your capture thread (approx. 30 FPS)
        time.sleep(0.03)


# =========================
# CHAMBER SCAN SETTINGS
# =========================
LA_TZ = pytz.timezone("America/Los_Angeles")

BASE_DIR        = "/home/khojahlab/SpringXYZ"
IMAGE_DIR       = os.path.join(BASE_DIR, "images")
IMAGES_BASE_DIR = os.path.join(BASE_DIR, "images_upload")

os.makedirs(IMAGE_DIR,       exist_ok=True)
os.makedirs(IMAGES_BASE_DIR, exist_ok=True)

STEPS_BETWEEN_CHAMBERS = 4000
STEP_DELAY             = 0.005

CHAMBER_NAMES = [
    "bottom_right",
    "bottom_center",
    "bottom_left",
    "top_left",
    "top_center",
    "top_right",
]

# Each entry: (axis, direction, steps) or None for the first chamber
CHAMBER_MOVEMENTS = [
    None,
    ("x", stepper.BACKWARD, STEPS_BETWEEN_CHAMBERS),
    ("x", stepper.BACKWARD, STEPS_BETWEEN_CHAMBERS),
    ("y", stepper.BACKWARD, STEPS_BETWEEN_CHAMBERS),
    ("x", stepper.FORWARD,  STEPS_BETWEEN_CHAMBERS),
    ("x", stepper.FORWARD,  STEPS_BETWEEN_CHAMBERS),
]

RETURN_HOME = [
    ("y", stepper.FORWARD, STEPS_BETWEEN_CHAMBERS),
]


def move_platform(axis, direction, steps):
    """Move x_motor or y_motor (imported from motor_control) a given number of steps."""
    motor = x_motor if axis == "x" else y_motor
    for _ in range(steps):
        motor.onestep(direction=direction, style=stepper.SINGLE)
        time.sleep(STEP_DELAY)
    motor.release()


def take_scan_photo(chamber_name):

    now_utc = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
    now = now_utc.astimezone(LA_TZ)

    timestamp = now.strftime("%Y%m%d_%H%M%S")

    os.makedirs(IMAGE_DIR, exist_ok=True)

    local_path = os.path.join(
        IMAGE_DIR,
        f"{chamber_name}_{timestamp}.jpg"
    )

    upload_dir = os.path.join(
        IMAGES_BASE_DIR,
        str(now.month).zfill(2),
        str(now.day).zfill(2),
        str(now.hour).zfill(2)
    )

    os.makedirs(upload_dir, exist_ok=True)

    upload_path = os.path.join(
        upload_dir,
        f"{chamber_name}_{timestamp}.jpg"
    )

    print(f"  [SCAN] Capturing {chamber_name}...")

    photo_taken = False

    try:

        with camera_lock:

            request = picam2.capture_request()

            frame = request.make_array("main")

            request.release()

        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        with Timer(f"CAPTURE_{chamber_name}"):
            success = cv2.imwrite(
                local_path,
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, 90]
            )

        if success and os.path.exists(local_path):

            print(
                f"  [SCAN] ✓ {local_path} "
                f"({os.path.getsize(local_path)} bytes)"
            )

            import shutil
            shutil.copy2(local_path, upload_path)

            photo_taken = True

        else:
            print("  [SCAN] ✗ Failed to save image")

    except Exception as e:
        print(f"  [SCAN] ✗ Capture error: {e}")

    return local_path if photo_taken else None

def run_scan():
    """Full 6-chamber automated scan. Camera stays running throughout."""
    global scan_status, led_state
    if scan_status["running"]:
        print("[SCAN] Already running, skipping.")
        return

    scan_status["running"]      = True
    scan_status["current_step"] = "Starting scan..."
    socketio.emit('scan_status', scan_status, namespace='/')

    GPIO.output(LED_PIN, GPIO.HIGH)
    led_state = True
    socketio.emit('led_state', {'state': True}, namespace='/')
    print("  [LED] ON for scan")

    with Timer("FULL_SCAN"):
        try:
            scan_start     = time.time()
            captured_files = []

            print("=" * 45)
            print("  AUTOMATED CHAMBER SCAN — 6 chambers")
            print("=" * 45)

            for i, chamber in enumerate(CHAMBER_NAMES):
                if CHAMBER_MOVEMENTS[i] is not None:
                    axis, direction, steps = CHAMBER_MOVEMENTS[i]
                    dir_name = "FORWARD" if direction == stepper.FORWARD else "BACKWARD"
                    scan_status["current_step"] = f"Moving to {chamber}..."
                    socketio.emit('scan_status', scan_status, namespace='/')
                    print(f"  Moving {axis.upper()} {dir_name} {steps} steps...")
                    move_platform(axis, direction, steps)
                    time.sleep(1.0)

                scan_status["current_step"] = f"Capturing {chamber} ({i+1}/6)..."
                socketio.emit('scan_status', scan_status, namespace='/')
                print(f"\n  Chamber {i+1}/6: {chamber}")
                fname = take_scan_photo(chamber)

                if fname:
                    captured_files.append(fname)
                    print(f"  ✓ Chamber {i+1} complete\n")
                else:
                    print(f"  ⚠ Chamber {i+1} photo failed\n")

            elapsed = time.time() - scan_start
            print(f"  Captures done: {len(captured_files)}/6 in {elapsed:.0f}s")

            print("\n" + "=" * 45)
            print("  RETURNING TO START POSITION (bottom_right)")
            print("=" * 45)

            scan_status["current_step"] = "Returning to start..."
            socketio.emit('scan_status', scan_status, namespace='/')

            try:
                for axis, direction, steps in RETURN_HOME:
                    dir_name = "FORWARD" if direction == stepper.FORWARD else "BACKWARD"
                    print(f"  Moving {axis.upper()} {dir_name} {steps} steps...")
                    move_platform(axis, direction, steps)
                    time.sleep(1.0)
                print("  ✓ Returned to bottom_right\n")
            except Exception as e:
                print(f"  ✗ Return home error: {e}")

        finally:
            GPIO.output(LED_PIN, GPIO.LOW)
            led_state = False
            socketio.emit('led_state', {'state': False}, namespace='/')
            print("  [LED] OFF after scan\n")

            now = datetime.datetime.now(LA_TZ)
            scan_status["running"]      = False
            scan_status["last_scan"]    = now.strftime("%Y-%m-%d %H:%M")
            scan_status["current_step"] = ""
            socketio.emit('scan_status', scan_status, namespace='/')
            print(f"  ✓ Scan complete at {scan_status['last_scan']}\n")


# =========================
# HOURLY SCAN SCHEDULER
# =========================
def scan_scheduler():
    while True:
        now     = datetime.datetime.now(LA_TZ)
        next_hr = (now + datetime.timedelta(hours=1)).replace(
                    minute=0, second=0, microsecond=0)
        wait    = (next_hr - now).total_seconds()
        scan_status["next_scan"] = next_hr.strftime("%Y-%m-%d %H:%M")
        socketio.emit('scan_status', scan_status, namespace='/')
        print(f"[SCAN] Next scan at {scan_status['next_scan']} "
              f"(in {wait/60:.1f} min)")
        time.sleep(wait)
        run_scan()

threading.Thread(target=scan_scheduler, daemon=True).start()


# =========================
# ORGANOID DETECTION
# =========================
detect_fn      = None
category_index = None


def load_detection_model():
    global detect_fn, category_index
    try:
        import tensorflow as tf
        from object_detection.utils import label_map_util
        os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
        PATH_TO_SAVED_MODEL = 'my_model/saved_model'
        if not os.path.exists(PATH_TO_SAVED_MODEL):
            print("[DETECTION] my_model/saved_model not found — detection disabled.")
            return
        print("[DETECTION] Loading TF model...")
        detect_fn      = tf.saved_model.load(PATH_TO_SAVED_MODEL)
        category_index = label_map_util.create_category_index_from_labelmap(
            'label_map.pbtxt', use_display_name=True)
        print("[DETECTION] Model ready.")
    except Exception as e:
        print(f"[DETECTION] Could not load model: {e}")

threading.Thread(target=load_detection_model, daemon=True).start()


def run_detection():
    """Run organoid detection on current frame"""
    global detect_fn, category_index
    
    try:
        # Get current frame
        with frame_lock:
            frame = latest_frame.copy() if latest_frame is not None else None
        
        if frame is None:
            print("[DETECTION] No frame available")
            socketio.emit('response3', {'data': None, 'error': 'No frame available'}, namespace='/')
            return
        
        result_frame = None
        count = 0
        
        # Try TensorFlow detection if model is available
        if detect_fn is not None:
            try:
                import tensorflow as tf
                import numpy as np
                from object_detection.utils import visualization_utils as viz_utils
                
                print("[DETECTION] Using TensorFlow model...")
                input_tensor = tf.convert_to_tensor(frame)[tf.newaxis, ...]
                detections = detect_fn(input_tensor)
                
                num_det = int(detections.pop('num_detections'))
                detections = {k: v[0, :num_det].numpy() for k, v in detections.items()}
                detections['num_detections'] = num_det
                detections['detection_classes'] = detections['detection_classes'].astype(np.int64)
                
                result_frame = frame.copy()
                viz_utils.visualize_boxes_and_labels_on_image_array(
                    result_frame,
                    detections['detection_boxes'],
                    detections['detection_classes'],
                    detections['detection_scores'],
                    category_index,
                    use_normalized_coordinates=True,
                    max_boxes_to_draw=200,
                    min_score_thresh=0.3,
                    agnostic_mode=False)
                
                count = num_det
                print(f"[DETECTION] TensorFlow found {count} organoids")
                
            except Exception as e:
                print(f"[DETECTION] TensorFlow error: {e}")
                print("[DETECTION] Falling back to simple detection...")
        
        # If TensorFlow didn't work or isn't available, use simple detection
        if result_frame is None:
            print("[DETECTION] Using simple OpenCV detection...")
            from simple_detection import simple_organoid_detection
            result_frame, count = simple_organoid_detection(frame)
        
        # Send result to frontend
        if result_frame is not None:
            _, buf = cv2.imencode('.jpg', result_frame)
            b64 = base64.b64encode(buf).decode('utf-8')
            socketio.emit('response3', {'data': b64, 'count': count}, namespace='/')
            print(f"[DETECTION] Detection complete. Found {count} objects")
        else:
            socketio.emit('response3', {'data': None, 'error': 'Detection failed'}, namespace='/')
            
    except Exception as e:
        print(f"[DETECTION] Error: {e}")
        import traceback
        traceback.print_exc()
        socketio.emit('response3', {'data': None, 'error': str(e)}, namespace='/')

# =========================================================
# ROUTES
# =========================================================
@app.route('/led_toggle')
def led_toggle():
    global led_state
    led_state = not led_state
    GPIO.output(LED_PIN, GPIO.HIGH if led_state else GPIO.LOW)
    log_event("LED_ON" if led_state else "LED_OFF")
    return str(led_state)

@app.route('/')
def index():
    return render_template('main.html')

@app.route('/video')
def video():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

# -- Motion --
@app.route('/up')
def up():
    log_event("MOVE_UP")
    threading.Thread(target=move_up).start(); return "OK"

@app.route('/down')
def down():
    log_event("MOVE_DOWN")
    threading.Thread(target=move_down).start(); return "OK"

@app.route('/left')
def left():
    log_event("MOVE_LEFT")
    threading.Thread(target=move_left).start(); return "OK"

@app.route('/right')
def right():
    log_event("MOVE_RIGHT")
    threading.Thread(target=move_right).start(); return "OK"

@app.route('/forward')
def forward():
    log_event("MOVE_FORWARD")
    threading.Thread(target=move_backward).start(); return "OK"   # Y axis intentionally inverted

@app.route('/backward')
def backward():
    log_event("MOVE_BACKWARD")
    threading.Thread(target=move_forward).start(); return "OK"    # Y axis intentionally inverted

@app.route('/stop')
def stop():
    release_all(); return "OK"

# -- Manual scan trigger --
@app.route('/scan_now')
def scan_now():
    threading.Thread(target=run_scan).start()
    return "OK"

# -- Scan status (polled by UI) --
@app.route('/scan_status')
def get_scan_status():
    return scan_status

# -- DC motors: run all channels --
@app.route('/update_parameters_motor')
def update_parameters_motor():
    try:
        speed    = float(request.args.get('motorspeed', 0))
        duration = float(request.args.get('spin_dur', 0))
        flow_dir = request.args.get('flow_dir', 'OFF').upper()

        system_params['motor_speed']    = speed
        system_params['spin_duration']  = duration
        system_params['flow_direction'] = flow_dir

        if flow_dir == 'OFF':
            threading.Thread(target=stop_all_motors).start()
        else:
            direction = 'FORWARD' if flow_dir in ('UP', 'RIGHT') else 'BACKWARD'
            threading.Thread(
                target=set_all_motors,
                args=(speed, direction, duration)
            ).start()

        print(f"[MOTOR ALL] speed={speed} dir={flow_dir} dur={duration}s")
    except Exception as e:
        print(f"[MOTOR ALL] Error: {e}")
    return "OK"

# -- DC motor: single channel --
@app.route('/dc_motor')
def dc_motor():
    try:
        ch        = int(request.args.get('ch', 1))
        speed     = float(request.args.get('speed', 0))
        direction = request.args.get('direction', 'FORWARD').upper()
        duration  = float(request.args.get('duration', 0))

        threading.Thread(
            target=set_motor,
            args=(ch, speed, direction, duration),
            daemon=True
        ).start()

        print(f"[DC CH{ch}] speed={speed} dir={direction} dur={duration}s")
    except Exception as e:
        print(f"[DC MOTOR] Error: {e}")
        return str(e), 400
    return "OK"

@app.route('/dc_motor_stop')
def dc_motor_stop():
    ch = request.args.get('ch')
    if ch:
        threading.Thread(target=stop_motor_single, args=(int(ch),), daemon=True).start()
    else:
        threading.Thread(target=stop_all_motors, daemon=True).start()
    return "OK"

@app.route('/dc_motor_states')
def dc_motor_states():
    return get_motor_states()

# -- Zoom / Focus --
@app.route('/update_parameters_zoom_focus')
def update_zoom_focus():
    system_params['zoom']  = request.args.get('zoom', 0)
    system_params['focus'] = request.args.get('focus', 0)
    print("ZOOM/FOCUS ->", system_params['zoom'], system_params['focus'])
    return "OK"

# -- Autofocus --
@app.route('/autofocus_camera_from_html')
def autofocus():
    print("AUTOFOCUS REQUEST")
    return "OK"

# -- System param sync --
@app.route('/get_system_parameters_from_html')
def get_system_parameters():
    socketio.emit('system_parameters_to_html',
                  {'data': {'data': system_params}}, namespace='/')
    socketio.emit('scan_status', scan_status, namespace='/')
    return "OK"

# -- Detection --
@app.route('/detect_organoid')
def detect_organoid():
    print("[DETECT] Starting organoid detection...")
    threading.Thread(target=run_detection).start()
    return jsonify({"success": True, "message": "Detection started"})

# -- Retrieve past image --
@app.route('/retrieve_past_image')
def retrieve_past_image():
    from image_download_script import fetch_image
    dt_str = request.args.get('datetime')
    try:
        # Parse the datetime from the frontend
        ts = datetime.datetime.strptime(dt_str, "%Y-%m-%dT%H:%M")
        ts = LA_TZ.localize(ts)
        
        print(f"[RETRIEVE] Searching for image at: {ts}")
        
        # Download image from Swift storage
        success = fetch_image(ts)
        
        if success:
            print(f"[RETRIEVE] Download successful, looking for file...")
            
            # The download script saves to images_downloaded/ with timestamp in filename
            # Look for the downloaded file
            import glob
            search_pattern = f"images_downloaded/*{ts.strftime('%d_%m_%Y_%H_%M')}*.png"
            matching_files = glob.glob(search_pattern)
            
            if matching_files:
                fpath = matching_files[0]
                print(f"[RETRIEVE] Found file: {fpath}")
                
                if os.path.exists(fpath):
                    img = cv2.imread(fpath)
                    if img is not None:
                        # Convert to jpg and send to frontend
                        _, buf = cv2.imencode('.jpg', img)
                        b64 = base64.b64encode(buf).decode('utf-8')
                        socketio.emit('response2', {'data': b64}, namespace='/')
                        return "OK"
            
            print(f"[RETRIEVE] File not found after download")
        else:
            print(f"[RETRIEVE] Download failed")
        
        # If we get here, image wasn't found
        socketio.emit('response2', {'data': False}, namespace='/')
        
    except Exception as e:
        print("retrieve_past_image error:", e)
        import traceback
        traceback.print_exc()
        socketio.emit('response2', {'data': False}, namespace='/')
    return "OK"
# -- Download zip --
@app.route('/prepare_download_images')
def prepare_download():
    from image_download_script import fetch_images_from_t1_to_t2
    from_str = request.args.get('from')
    to_str   = request.args.get('to')
    try:
        print(f"[DOWNLOAD] Preparing images from {from_str} to {to_str}")
        
        t1 = LA_TZ.localize(datetime.datetime.strptime(from_str, "%Y-%m-%dT%H:%M"))
        t2 = LA_TZ.localize(datetime.datetime.strptime(to_str,   "%Y-%m-%dT%H:%M"))
        
        zip_path = fetch_images_from_t1_to_t2(t1, t2)
        
        if zip_path and os.path.exists(zip_path):
            app.config['LAST_ZIP'] = zip_path
            print(f"[DOWNLOAD] Zip created: {zip_path}")
            return jsonify({"success": True})
        else:
            print("[DOWNLOAD] No images found in range")
            return jsonify({"success": False, "error": "No images found in this time range"})
            
    except Exception as e:
        print("prepare_download error:", e)
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)})

@app.route('/download_images')
def download_images():
    zip_path = app.config.get('LAST_ZIP')
    if zip_path and os.path.exists(zip_path):
        return send_file(zip_path, as_attachment=True)
    return "No zip ready", 404


def check_directories():
    dirs_to_check = [IMAGE_DIR, IMAGES_BASE_DIR, "/tmp"]
    print("\n" + "="*50)
    print("DIRECTORY PERMISSIONS CHECK")
    print("="*50)
    for d in dirs_to_check:
        try:
            os.makedirs(d, exist_ok=True)
            test_file = os.path.join(d, "test_write.txt")
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
            print(f"✓ {d} - EXISTS and WRITABLE")
        except PermissionError:
            print(f"✗ {d} - PERMISSION DENIED")
            print(f"  Fix with: sudo chmod 777 {d}")
        except Exception as e:
            print(f"✗ {d} - ERROR: {e}")
    try:
        from picamera2 import Picamera2
        print(f"✓ picamera2 available")
    except Exception:
        print(f"✗ picamera2 NOT AVAILABLE")
    print("="*50 + "\n")


# =========================
# RUN
# =========================
if __name__ == '__main__':
    check_directories()
    from image_upload_script import set_upload_time
    threading.Thread(target=set_upload_time, daemon=True).start()
    print("Server running at http://0.0.0.0:5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False,
                 allow_unsafe_werkzeug=True)
