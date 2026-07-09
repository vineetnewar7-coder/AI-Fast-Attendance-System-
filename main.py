import logging, warnings
logging.getLogger("streamlit").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", category=UserWarning)

import streamlit as st
st.set_page_config(page_title="AI Attendance System", layout="wide")

import os, time, base64, threading, queue
import cv2, numpy as np
import face_recognition
import pandas as pd
import datetime

import config
import database
import face_logic
import notifications
import ui

# Initialize a thread-safe Queue and worker for Twilio messaging.
# Running this as a daemon thread prevents notification delays from blocking the UI.
if "wa_q" not in st.session_state:
    st.session_state.wa_q = queue.Queue()

if "wa_started" not in st.session_state:
    threading.Thread(target=notifications._wa_worker, args=(st.session_state.wa_q,), daemon=True).start()
    st.session_state.wa_started = True

# The fragment decorator executes this UI sub-tree independently at 1Hz.
# This prevents costly whole-page reruns and stabilizes webcam resource polling.
@st.fragment(run_every=1)
def camera_fragment(tid, subject, search, filt):
    # Fetch pre-loaded face embeddings for the active tenant
    known_enc   = st.session_state.get(f"enc_{tid}", [])
    class_names = st.session_state.get(f"nam_{tid}", [])
    known_np    = st.session_state.get(f"np_{tid}",  np.empty((0,128)))

    # keep the camera power switch state local to this fragment to avoid resetting other page element
    run = st.checkbox("▶️  **Power On Camera**", key="cam_on")

    if not run:
        face_logic.release_camera()
        st.session_state.pop("_frame_i", None)
        st.session_state.pop("last_faces", None)
        col_l, col_r = st.columns([1,1])
        with col_l: st.info("ℹ️ Tick **Power On Camera** above to start.")
        with col_r:
            df = st.session_state.get("att_df", pd.DataFrame(columns=['Name','Roll','Phone','Status']))
            ui.show_table(df, search, filt)
        return

    # Persist the capture object across fragment execution steps
    cap = st.session_state.get("_cap")
    if cap is None or not cap.isOpened():
        cap = face_logic.open_camera()
        if cap is None:
            st.error("❌ Camera not found. Ensure it is connected and not used by another app.")
            return
        st.session_state._cap = cap

    # Extract raw image matrix from hardware source
    ok, img = cap.read()
    if not ok or img is None:
        st.warning("⚠️ No frame — camera may be busy. Uncheck and re-check to retry.")
        return

    # Frame processing scheduler to limit CPU utilization
    fi = st.session_state.get("_frame_i", 0) + 1
    st.session_state._frame_i = fi

    # Compute face locations and embeddings on every Nth frame to preserve computational resources
    if fi % config.PROCESS_EVERY_N == 0 or "last_faces" not in st.session_state:
        imgS    = cv2.resize(img,(0,0),None,config.PROCESS_SCALE,config.PROCESS_SCALE)
        img_rgb = cv2.cvtColor(imgS, cv2.COLOR_BGR2RGB)

        yolo = st.session_state.get("yolo_model")
        face_locs = (face_logic.yolo_locs(yolo, imgS) if yolo
                     else face_recognition.face_locations(img_rgb, model="hog"))
        face_encs = (face_recognition.face_encodings(img_rgb, face_locs,
                     num_jitters=1, model="small") if face_locs else [])

        fst    = st.session_state.setdefault("fst", {})
        lmt    = st.session_state.setdefault("lmt", {})
        active = set()
        faces  = []

        for enc, loc in zip(face_encs, face_locs):
            lbl      = face_logic.match_face(enc, known_np, class_names)
            verified = False; elapsed=0.0; disp="Unknown"

            if lbl:
                disp=database._disp(lbl); active.add(lbl)
                roll=database._roll(lbl); now=time.time()
                sk  = f"done_{subject}_{roll}"
                if not st.session_state.get(sk):
                    fst.setdefault(lbl, now)
                    elapsed = now - fst[lbl]
                    # Log attendance record only after a continuous detection threshold is crossed
                    if elapsed >= config.SCAN_DELAY:
                        verified = True
                        if (now - lmt.get(lbl,0)) > config.MARK_COOLDOWN:
                            ok2, phone = database.mark_present(tid, subject, lbl)
                            if ok2:
                                lmt[lbl]=now
                                st.session_state.att_df = database.load_attendance(tid, subject)
                                st.toast(f"🎯 Verified! {disp} marked Present. Processing alert...")
                                if phone:
                                    st.session_state.wa_q.put((phone,disp,subject,tid,lbl))
                else: verified=True

            faces.append({"disp":disp,"loc":loc,"verified":verified,"elapsed":elapsed})

        for lbl2 in [x for x in fst if x not in active]: del fst[lbl2]
        st.session_state.last_faces = faces

    # Render bounding boxes, scanning feedback, and labels directly onto the frame
    s = config.PROCESS_SCALE
    for fi_d in st.session_state.get("last_faces",[]):
        top,right,bottom,left = fi_d["loc"]
        x1,y1=int(left/s),int(top/s); x2,y2=int(right/s),int(bottom/s)
        d=fi_d["disp"]
        if d=="Unknown":
            cv2.rectangle(img,(x1,y1),(x2,y2),(0,0,255),2)
            cv2.putText(img,"Unknown",(x1+4,max(18,y1-8)),cv2.FONT_HERSHEY_SIMPLEX,.65,(255,255,255),2)
        elif fi_d["verified"]:
            cv2.rectangle(img,(x1,y1),(x2,y2),(0,220,0),2)
            cv2.putText(img,f"{d} PRESENT",(x1+4,max(18,y1-8)),cv2.FONT_HERSHEY_SIMPLEX,.65,(0,220,0),2)
        else:
            bh=y2-y1; t=time.time()%1.2; rt=(2*t/1.2) if t<.6 else 2*(1.2-t)/1.2
            cv2.line(img,(x1+4,int(y1+rt*bh)),(x2-4,int(y1+rt*bh)),(50,255,255),2)
            cv2.rectangle(img,(x1,y1),(x2,y2),(255,220,0),2)
            cv2.putText(img,f"Scanning {fi_d['elapsed']:.1f}s",(x1+4,max(18,y1-8)),
                        cv2.FONT_HERSHEY_SIMPLEX,.6,(255,220,0),2)

    # Output processed frame and filtered session attendance list side-by-side
    col_l, col_r = st.columns([1,1])
    with col_l:
        _, buf = cv2.imencode('.jpg',img,[cv2.IMWRITE_JPEG_QUALITY,75])
        st.markdown(
            f'<img src="data:image/jpeg;base64,{base64.b64encode(buf).decode()}" '
            f'style="width:100%;border-radius:8px;border:2px solid #333">',
            unsafe_allow_html=True)
    with col_r:
        df = st.session_state.get("att_df", pd.DataFrame(columns=['Name','Roll','Phone','Status']))
        ui.show_table(df, search, filt)

# Tenant registration and login interface components
def show_auth():
    st.markdown("""
    <h1 style='text-align:center;margin-top:60px'>🎓 AI Attendance System</h1>
    <p style='text-align:center;color:#888'>Multi-College · Subject-wise · YOLOv8</p><hr>
    """, unsafe_allow_html=True)
    t1, t2 = st.tabs(["🔐 Login","📝 Register College"])
    with t1:
        with st.form("lf"):
            code=st.text_input("College Code"); pw=st.text_input("Password",type="password")
            if st.form_submit_button("Login",use_container_width=True):
                if code and pw:
                    t=database.tenant_login(code,pw)
                    if t: st.session_state.tenant=t; st.rerun()
                    else: st.error("❌ Wrong code / password.")
                else: st.warning("Fill both fields.")
    with t2:
        with st.form("rf"):
            rn=st.text_input("College Name"); rc=st.text_input("Code (no spaces)")
            rp=st.text_input("Password",type="password"); rp2=st.text_input("Confirm Password",type="password")
            if st.form_submit_button("Register",use_container_width=True):
                if not all([rn,rc,rp]): st.error("All fields required.")
                elif ' ' in rc:         st.error("No spaces in code.")
                elif rp!=rp2:           st.error("Passwords don't match.")
                else:
                    ok,msg=database.tenant_register(rn,rc,rp); (st.success if ok else st.error)(msg)

# Setup schemas and check application credentials
database.init_db()

if "tenant" not in st.session_state:
    show_auth(); st.stop()

tenant = st.session_state.tenant
tid    = tenant["id"]

# Reset volatile session states to rebuild lists correctly on a new login event
_att_boot = f"_att_boot_{tid}"
if _att_boot not in st.session_state:
    database.reset_today_attendance(tid)
    st.session_state[_att_boot] = True
    st.session_state.pop("att_df", None)
    for k in [k for k in st.session_state if k.startswith("done_")]:
        del st.session_state[k]

# Sidebar configuration, logout handling, and dataset management
st.sidebar.markdown(f"### 🏫 {tenant['name']}")
st.sidebar.caption(f"Code: `{tenant['code']}`")
if st.sidebar.button("🚪 Logout"):
    face_logic.release_camera()
    for k in list(st.session_state): del st.session_state[k]
    st.rerun()

st.sidebar.markdown("---")
page = st.sidebar.radio("📌 Navigation",[
    "📷 Take Attendance","👥 Manage Students","📚 Manage Subjects","📊 History & Reports"
])

st.sidebar.markdown("---")
st.sidebar.markdown("#### 📸 Upload Face Photo")
st.sidebar.caption("`NAME.jpg` or `NAME_ROLL.jpg`  e.g. `VINEET.jpg`")
up = st.sidebar.file_uploader("Choose photo",type=["jpg","jpeg","png"],key="uploader")
if up:
    processed_key = f"processed_{up.name}_{up.size}"
    if not st.session_state.get(processed_key):
        path = os.path.join(face_logic._img_dir(tid), up.name)
        with open(path, 'wb') as f:
            f.write(up.read())
        # Delete local cache files to force generation of new facial profiles
        ep = face_logic._enc_path(tid)
        if os.path.exists(ep):
            os.remove(ep)
        for k in [f"enc_{tid}", f"nam_{tid}", f"np_{tid}"]:
            st.session_state.pop(k, None)
        st.session_state[processed_key] = True
        st.sidebar.success(f"✅ {up.name} uploaded!")
        st.rerun()

# Student directory and registration interface
if page=="👥 Manage Students":
    face_logic.release_camera()
    st.title("👥 Manage Students")

    # Fetch and display persistent transaction logs
    if "_stu_msg" in st.session_state:
        mtype, mtxt = st.session_state.pop("_stu_msg")
        (st.success if mtype == "ok" else st.error)(mtxt)

    c1, c2 = st.columns([1, 1])

    with c1:
        st.subheader("Add / Update Student")
        with st.form("stu_form"):
            sn = st.text_input("Full Name")
            sr = st.text_input("Roll Number")
            sp = st.text_input("Phone (+91...)")
            if st.form_submit_button("💾 Save Student", use_container_width=True):
                if sn and sr:
                    ok, msg = database.save_student(tid, sn, sr, sp)
                    st.session_state._stu_msg = ("ok" if ok else "err", msg)
                    st.session_state.pop("att_df", None)
                    st.rerun()
                else:
                    st.warning("Name + Roll required.")
        st.caption("💡 Tip: to avoid duplicate rows, name your face photo `VINEET_102.jpg` "
                   "(with roll number). A plain `VINEET.jpg` auto-assigns roll `NR-VINEET` "
                   "only if no student named VINEET exists yet.")

    with c2:
        st.subheader("Student List")
        df_s = database.get_students(tid)
        if df_s.empty:
            st.info("No students yet. Add one using the form.")
        else:
            st.dataframe(df_s, use_container_width=True, hide_index=True)

            st.markdown("---")
            st.markdown("**Delete a student:**")
            roll_list = df_s["Roll"].tolist()
            dr = st.selectbox("Select Roll Number", roll_list, key="del_roll_select")
            matched = df_s[df_s["Roll"] == dr]
            if not matched.empty:
                st.caption(f"Selected: **{matched.iloc[0]['Name']}** — Roll {dr}")
            if st.button("🗑️ Delete This Student", type="primary", use_container_width=True):
                database.del_student(tid, dr)
                st.session_state._stu_msg = ("ok", f"✅ Deleted student with roll **{dr}**")
                st.session_state.pop("att_df", None)
                st.rerun()

# Course subject registration configuration page
elif page=="📚 Manage Subjects":
    face_logic.release_camera()
    st.title("📚 Manage Subjects")
    subs=database.get_subjects(tid)
    c1,c2=st.columns([1,1])
    with c1:
        st.subheader("Add Subject")
        with st.form("asub"):
            sn2=st.text_input("Subject Name",placeholder="e.g. Mathematics")
            if st.form_submit_button("➕ Add"):
                if sn2.strip(): ok,msg=database.add_subject(tid,sn2); (st.success if ok else st.error)(msg); st.rerun()
                else: st.warning("Enter a name.")
    with c2:
        st.subheader("Current Subjects")
        if not subs: st.info("No subjects yet.")
        else:
            for s in subs:
                cs1,cs2=st.columns([3,1])
                cs1.write(f"📖 {s}")
                if cs2.button("🗑️",key=f"ds_{s}"):
                    database.del_subject(tid,s); st.rerun()

# Archive search, filtering, and reporting modules
elif page=="📊 History & Reports":
    face_logic.release_camera()
    st.title("📊 History & Reports")
    subs=database.get_subjects(tid)
    if not subs: st.warning("Add subjects first."); st.stop()
    c1,c2=st.columns(2)
    with c1: hd=st.date_input("📅 Date",datetime.date.today())
    with c2: hs=st.selectbox("📚 Subject",subs)
    df_h=database.load_history(tid,hd,hs)
    if df_h.empty: st.info(f"No data for **{hs}** on **{hd}**.")
    else:
        tot=len(df_h); pc=(df_h['Status']=='P').sum(); ac=(df_h['Status']=='A').sum()
        m1,m2,m3=st.columns(3); m1.metric("👥 Total",tot); m2.metric("✅ Present",pc); m3.metric("❌ Absent",ac)
        st.markdown(f"### {hs} — {hd.strftime('%d %b %Y')}")
        st.dataframe(df_h.style.map(ui._badge,subset=['Status']),use_container_width=True,hide_index=True)
        st.download_button("⬇️ Download CSV",df_h.to_csv(index=False).encode(),
                           f"attendance_{hs}_{hd}.csv","text/csv")

# Capture loop entry and core configuration menu
elif page=="📷 Take Attendance":
    st.title(f"📷 Take Attendance — {tenant['name']}")

    subs=database.get_subjects(tid)
    if not subs:
        st.warning("⚠️ Add subjects in **Manage Subjects** first."); st.stop()

    # Layout inputs controlling the active context of the camera stream
    cc1,cc2=st.columns([2,1])
    with cc1: subject=st.selectbox("📚 Select Subject",subs,key="sel_sub")
    with cc2: search =st.text_input("🔍 Search Name",key="srch")

    filt=st.radio("Filter",["All Records","Present Only","Absent Only"],horizontal=True,key="flt")

    # Flush session metrics when changing subject target
    if st.session_state.get("_cur_sub") != subject:
        st.session_state._cur_sub = subject
        st.session_state.fst      = {}
        st.session_state.lmt      = {}
        st.session_state.pop("last_faces",None)
        st.session_state.pop("_frame_i",None)
        for k in [k for k in st.session_state if k.startswith("done_")]: del st.session_state[k]
        st.session_state.att_df = database.load_attendance(tid, subject)

    # Force re-indexing of facial recognition assets on request
    if st.button("🔁 Reload Face Encodings"):
        with st.spinner("Reloading face encodings..."):
            face_logic.reload_faces(tid)
            database.ensure_students(tid, st.session_state.get(f"nam_{tid}",[]))
            st.session_state.att_df = database.load_attendance(tid, subject)
        st.success(f"✅ {len(st.session_state.get(f'enc_{tid}',[]))} face(s) loaded.")
        st.rerun()

    # Pre-index target descriptors on application startup
    if not face_logic.faces_loaded(tid):
        with st.spinner("Loading face encodings..."):
            face_logic.reload_faces(tid)
            database.ensure_students(tid, st.session_state.get(f"nam_{tid}",[]))
        if "att_df" not in st.session_state:
            st.session_state.att_df = database.load_attendance(tid, subject)

    names_loaded = st.session_state.get(f"nam_{tid}", [])
    if names_loaded:
        st.info(f"✅ {len(names_loaded)} face(s) loaded: **{', '.join(names_loaded)}**")
    else:
        st.warning("⚠️ No face photos. Upload via sidebar (`NAME.jpg` or `NAME_ROLL.jpg`).")

    if "att_df" not in st.session_state:
        st.session_state.att_df = database.load_attendance(tid, subject)

    # Lazily initialize deep learning detection model to conserve GPU RAM limits
    if "yolo_model" not in st.session_state:
        with st.spinner("Loading YOLOv8 (first time only)..."):
            st.session_state.yolo_model = face_logic._try_load_yolo()
        if st.session_state.yolo_model: st.success("✅ YOLOv8 ready.")

    st.markdown("---")

    # Pass configuration to isolated camera rendering segment
    camera_fragment(tid, subject, search, filt)