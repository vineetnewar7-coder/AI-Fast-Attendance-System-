import os
from pathlib import Path
import streamlit as st

# --- Application Performance and Threshold Parameters ---
IMAGE_BASE     = 'Images'
TOLERANCE      = 0.50
PROCESS_SCALE   = 0.50
PROCESS_EVERY_N = 3       # Decouples frame extraction from inference to prevent pipeline lag on standard CPUs
MARK_COOLDOWN  = 60       # seconds
SCAN_DELAY     = 2.5      # Continuous frame verification window to prevent accidental reads from passing traffic
MAX_FACES      = 30
YOLO_WEIGHTS   = 'yolov8n-face.pt'
YOLO_URLS = [
    'https://github.com/lindevs/yolov8-face/releases/latest/download/yolov8n-face-lindevs.pt',
    'https://github.com/YapaLab/yolo-face/releases/download/1.0.0/yolov8n-face.pt',
]
PROJECT_DIR = Path(__file__).resolve().parent

# --- Environment Configuration & Secrets Management ---
def _secret(k, d=""):
    try:    return st.secrets[k]
    except: return os.environ.get(k, d) # Fall back to environment variables for local CLI testing profiles

DATABASE_URL = _secret("DATABASE_URL")
T_SID  = _secret("TWILIO_ACCOUNT_SID")
T_TOK  = _secret("TWILIO_AUTH_TOKEN")
T_FROM = _secret("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")