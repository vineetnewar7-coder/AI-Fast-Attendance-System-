import os
import streamlit as st
import config

# --- Dummy Implementations for Cloud Admin Portal ---
# This bypasses C++ compiling errors and heavy dependencies on the cloud server.

def _img_dir(tid):
    d = os.path.join(config.IMAGE_BASE, str(tid))
    os.makedirs(d, exist_ok=True)
    return d

def _enc_path(tid): 
    return os.path.join(config.IMAGE_BASE, f'enc_{tid}.pkl')

def build_encodings(tid):
    """Dummy encoding builder returning empty sets to bypass cloud processing."""
    return [], []

def reload_faces(tid):
    """Dummy reloader for cloud-side session state."""
    st.session_state[f"enc_{tid}"]  = []
    st.session_state[f"nam_{tid}"]  = []
    st.session_state[f"np_{tid}"]   = None

def faces_loaded(tid): 
    return False

def match_face(enc, np_arr, names):
    return None

# --- Dummy YOLO Helpers ---
_YOLO = None

def _try_load_yolo():
    return None

def yolo_locs(model, bgr):
    return []

# --- Dummy Camera Controls ---
def open_camera():
    return None

def release_camera():
    pass
