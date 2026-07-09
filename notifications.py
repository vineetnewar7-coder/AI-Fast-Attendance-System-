import datetime, time
from twilio.rest import Client
import config
import database

# The message queue and background thread are initialized inside main.py using st.session_state.
# Since Python modules are cached on the first import, initializing them here would share
# a single worker thread across all active user sessions, causing state leakage.
# Keeping initialization in main.py ensures isolated background workers for each browser session.
def _send_wa(phone, name, subject):
    if not config.T_TOK or not config.T_SID:
        return
    p = str(phone).strip().split('.')[0]
    if not p.startswith('+'):
        p = '+91' + p
    body = (
        f"ATTENDANCE ALERT\n"
        f"Dear Parent, your ward *{name}* is PRESENT in *{subject}* today.\n"
        f"Date: {datetime.date.today():%d-%b-%Y}  "
        f"Time: {datetime.datetime.now():%I:%M %p}\n— Administration"
    )
    try:
        Client(config.T_SID, config.T_TOK).messages.create(
            from_=config.T_FROM, body=body, to=f"whatsapp:{p}")
    except Exception as e:
        print(f"[Twilio] {e}")

def _wa_worker(q):
    while True:
        item = q.get()
        try:
            if item:
                phone, name, subj, tid, lbl = item
                time.sleep(1)
                _send_wa(phone, name, subj)
                database.flag_msg_sent(tid, subj, lbl)
        except Exception:
            pass
        finally:
            q.task_done()