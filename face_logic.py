import os, pickle, urllib.request
import cv2, numpy as np
import face_recognition
import streamlit as st
import config

# --- Facial Feature Extraction and Serialization ---
def _img_dir(tid):
    d = os.path.join(config.IMAGE_BASE, str(tid)); os.makedirs(d, exist_ok=True); return d
def _enc_path(tid): return os.path.join(config.IMAGE_BASE, f'enc_{tid}.pkl')

def build_encodings(tid):
    """Generates face descriptors from disk, utilizing an incremental pickle cache to bypass reprocessing unchanged images."""
    img_dir = _img_dir(tid)
    files   = [f for f in os.listdir(img_dir) if f.lower().endswith(('.jpg','.jpeg','.png'))]
    saved   = {}
    ep      = _enc_path(tid)
    if os.path.exists(ep):
        try:
            with open(ep,'rb') as f: saved = pickle.load(f)
        except: pass

    cur = {os.path.splitext(f)[0] for f in files}
    for k in list(saved):       # Prune records from the cache that no longer exist on disk
        if k not in cur: del saved[k]

    updated = False
    for fname in files:
        name = os.path.splitext(fname)[0]
        if name in saved: continue
        img = cv2.imread(os.path.join(img_dir, fname))
        if img is None: continue
        encs = face_recognition.face_encodings(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        if encs: saved[name] = encs[0]; updated = True

    if updated:
        with open(ep,'wb') as f: pickle.dump(saved, f)

    names = list(saved.keys())
    return [saved[n] for n in names], names

def reload_faces(tid):
    enc, names = build_encodings(tid)
    st.session_state[f"enc_{tid}"]  = enc
    st.session_state[f"nam_{tid}"]  = names
    st.session_state[f"np_{tid}"]   = np.array(enc) if enc else np.empty((0,128))

def faces_loaded(tid): return f"enc_{tid}" in st.session_state

def match_face(enc, np_arr, names):
    if np_arr.shape[0] == 0: return None
    d = np.linalg.norm(np_arr - enc, axis=1)
    i = int(np.argmin(d))
    return names[i] if d[i] <= config.TOLERANCE else None

# --- YOLO Object Detection & Formatting Helpers ---
_YOLO = None

def _try_load_yolo():
    global _YOLO
    if _YOLO: return _YOLO
    try:
        from ultralytics import YOLO
        wp = config.PROJECT_DIR / config.YOLO_WEIGHTS
        if not wp.is_file():
            # Automatically fetch pre-trained weights if local model assets are missing
            for url in config.YOLO_URLS:
                try: urllib.request.urlretrieve(url, wp); break
                except: continue
        if wp.is_file():
            _YOLO = YOLO(str(wp))
    except Exception as e:
        print(f"Model load failed: {e}")
    return _YOLO

def yolo_locs(model, bgr):
    h,w = bgr.shape[:2]
    res = model.predict(bgr,verbose=False,conf=0.45,iou=0.5,imgsz=640,max_det=config.MAX_FACES)[0]
    out = []
    if res.boxes is None: return out
    for box in res.boxes.xyxy.cpu().numpy():
        x1,y1,x2,y2 = map(int,box[:4])
        x1,y1=max(0,x1),max(0,y1); x2,y2=min(w-1,x2),min(h-1,y2)
        if (x2-x1)<20 or (y2-y1)<20: continue
        # Rearrange bounding box coordinates to (top, right, bottom, left) to match face_recognition requirements
        out.append((y1,x2,y2,x1))
    return out

# --- Hardware Capture & Frame Buffering ---
def open_camera():
    # Use direct-show APIs on Windows to bypass slow device startup latencies
    flags = cv2.CAP_DSHOW if os.name=="nt" else 0
    for idx in (0,1,2):
        cap = cv2.VideoCapture(idx, flags)
        if cap.isOpened():
            # Constrain buffer queue depth to 1 to guarantee real-time frame evaluation
            cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT,480)
            cap.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc(*'MJPG'))
            return cap
        cap.release()
    return None

def release_camera():
    cap = st.session_state.pop("_cap", None)
    if cap:
        try: cap.release()
        except: pass