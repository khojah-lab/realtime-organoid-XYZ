# This is Just for Testing Controls on main.html page, Note this is DeepSeek Code NOT FINAL code

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