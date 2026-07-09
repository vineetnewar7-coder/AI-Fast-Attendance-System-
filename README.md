# Multi-Tenant AI Face Recognition Attendance System

A high-speed, automated subject-wise attendance tracking system developed using **Streamlit, YOLOv8-Face, OpenCV, and Cloud PostgreSQL**. This project automates the manual attendance process, supports multi-college tenant registration, and provides headless real-time parent notifications via Twilio's WhatsApp API.

##  Project Overview
This system is designed for modern educational institutions. Each college can register and manage their own students, subjects, and attendance sheets. Biometric recognition is processed locally at high FPS, while transactional updates and automated WhatsApp alerts are executed securely on cloud infrastructure.

## ## Features
* **YOLOv8-Face Detection:** High-accuracy, robust face detection optimized for classroom crowds.
* **SaaS Multi-Tenancy:** Secure login/registration panels to keep each college's roster and subjects isolated.
* **Subject-Wise Tracking:** Flexibility to select, add, and track attendance for specific subjects.
* **Cloud PostgreSQL Integration:** Production-ready relational database schema hosted on Neon.tech.
* **Asynchronous Twilio Alerts:** Headless WhatsApp messages dispatched automatically via background task queues.
* **Non-blocking UI:** Smooth live video rendering using Streamlit fragments without full-page reloads.

## ## Prerequisites
To run this project, ensure you have the following installed:
1. Python 3.8+
2. Visual Studio Build Tools (with "Desktop Development with C++" workload).
3. CMake.
4. Active Twilio Developer Account.
5. Active Neon.tech or Supabase PostgreSQL database instance.

## ## Setup Instructions


1. **Clone the repository:**
   git clone https://github.com/vineetnewar7-coder/AI-Fast-Attendance-System-.git
   cd AI-Fast-Attendance-System-

2. **Install dependencies:**
   pip install -r requirements.txt

   3. **Configure Environment Secrets:**
   - Create a folder named `.streamlit` in the root directory.
   - Inside `.streamlit/`, create a file named `secrets.toml`.
   - Add your credentials in the following format:
     ```toml
     DATABASE_URL = "your_postgres_db_url"
     TWILIO_ACCOUNT_SID = "your_sid"
     TWILIO_AUTH_TOKEN = "your_token"
     TWILIO_WHATSAPP_FROM = "whatsapp:+14155238886"
     ```

4. ## Configure Data
- Add student photos in the `Images/` folder (Format: `NAME_ROLL.jpg`). 
- Students can be registered and managed directly through the application's dashboard UI, which automatically syncs with the PostgreSQL database.

5. **Run the system:**
   streamlit run main.py

   ## Project Structure
The project is modularized into the following files for clean separation of concerns:
- `main.py`: Main entry point and camera loop controller.
- `config.py`: Central configuration for paths and system settings.
- `face_logic.py`: Handles YOLOv8 detection and encoding logic.
- `database.py`: Manages PostgreSQL database interactions.
- `notifications.py`: Handles automated WhatsApp alert delivery.
- `ui.py`: Manages Streamlit dashboard layout and styling.

