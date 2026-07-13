import logging, warnings
logging.getLogger("streamlit").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", category=UserWarning)

import streamlit as st
st.set_page_config(page_title="Attendance Admin Portal", layout="wide")

import os, time, base64, threading, queue
import pandas as pd
import datetime

import config
import database
import notifications
import ui

# Initialize a thread-safe Queue and worker for Twilio messaging.
# Running this as a daemon thread prevents notification delays from blocking the UI.
if "wa_q" not in st.session_state:
    st.session_state.wa_q = queue.Queue()

if "wa_started" not in st.session_state:
    threading.Thread(target=notifications._wa_worker, args=(st.session_state.wa_q,), daemon=True).start()
    st.session_state.wa_started = True

# Tenant registration and login interface components
def show_auth():
    st.markdown("""
    <h1 style='text-align:center;margin-top:60px'>🎓 Attendance Admin Portal</h1>
    <p style='text-align:center;color:#888'>Multi-College · Subject-wise · Cloud Administration Panel</p><hr>
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
    for k in list(st.session_state): del st.session_state[k]
    st.rerun()

st.sidebar.markdown("---")
page = st.sidebar.radio("📌 Navigation",[
    "👥 Manage Students","📚 Manage Subjects","📊 History & Reports","🛠️ Recruiter Demo Tools"
])

# Student directory and registration interface
if page=="👥 Manage Students":
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
        st.caption("💡 Tip: Manage student records here. The local edge camera client will sync automatically with these records.")

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

# Recruiter & Demo Simulator Section
elif page == "🛠️ Recruiter Demo Tools":
    st.title("🛠️ Recruiter Demo Tools")
    st.markdown("""
    Welcome to the **Developer Demo Control Panel**. Since this cloud-deployed web app is an administration panel 
    and doesn't directly run a physical camera, you can use these tools to simulate the entire end-to-end pipeline 
    (Database insertions, real-time status updates, and WhatsApp notifications).
    """)
    st.markdown("---")
    
    c1, c2 = st.columns([1, 1])
    
    with c1:
        st.subheader("1. Populate PostgreSQL with Mock Data")
        st.write("Clicking this button will seed your Neon PostgreSQL tables with a list of mock students, courses, and generated attendance logs. This lets you inspect populated data in other tabs immediately.")
        if st.button("📥 Seeding Mock Database", use_container_width=True):
            with st.spinner("Populating tables..."):
                ok, msg = database.generate_mock_data(tid)
                if ok:
                    st.success(msg)
                    st.session_state.pop("att_df", None)
                else:
                    st.error(msg)
    
    with c2:
        st.subheader("2. Simulate Face Match & Twilio Alerts")
        st.write("Select a registered student and subject below to manually simulate a successful face recognition match. This will mark the student **Present** in the database and trigger a real WhatsApp alert using Twilio.")
        
        df_s = database.get_students(tid)
        subs = database.get_subjects(tid)
        
        if df_s.empty or not subs:
            st.warning("⚠️ Please populate mock data first using the left panel or register a student/subject.")
        else:
            student_list = []
            for idx, r in df_s.iterrows():
                student_list.append(f"{r['Name']} (Roll: {r['Roll']})")
            
            sel_student = st.selectbox("Select Student to Simulate", student_list)
            sel_sub = st.selectbox("Select Subject", subs)
            
            # Extract raw parameters safely
            try:
                roll_part = sel_student.split("(Roll: ")[1].replace(")", "").strip()
                name_part = sel_student.split(" (Roll:")[0].strip()
            except IndexError:
                roll_part = ""
                name_part = ""
            
            if st.button("⚡ Trigger Swipe & Send WhatsApp Alert", use_container_width=True):
                if roll_part and sel_sub:
                    with st.spinner("Processing trigger..."):
                        label_format = f"{name_part.replace(' ', '_')}_{roll_part}"
                        
                        sk = f"done_{sel_sub}_{roll_part}"
                        st.session_state.pop(sk, None)
                        
                        ok, phone = database.mark_present(tid, sel_sub, label_format)
                        if ok:
                            st.success(f"🎯 Successfully marked {name_part} (Roll: {roll_part}) as PRESENT!")
                            st.session_state.att_df = database.load_attendance(tid, sel_sub)
                            if phone:
                                st.session_state.wa_q.put((phone, name_part, sel_sub, tid, label_format))
                                st.info(f"📨 WhatsApp alert queued for registered parent number: `{phone}`")
                            else:
                                st.warning("⚠️ Attendance marked, but no phone number found or message already dispatched.")
                        else:
                            st.warning("ℹ️ Already marked Present for this subject today.")
                else:
                    st.error("Error parsing student parameters.")
