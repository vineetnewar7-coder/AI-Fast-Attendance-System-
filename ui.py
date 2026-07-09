import streamlit as st

# ─────────────────────────────────────────────────────────
#  UI helpers
# ─────────────────────────────────────────────────────────
def _badge(v):
    if v=='P': return 'background:#1a4731;color:#6fcf97;font-weight:bold;text-align:center;border-radius:4px'
    if v=='A': return 'background:#4a1020;color:#eb5757;font-weight:bold;text-align:center;border-radius:4px'
    return ''

def show_table(df, search="", filt="All Records"):
    if df.empty: st.info("No students. Add via **Manage Students** or upload a face photo."); return
    tot=len(df); pc=(df['Status']=='P').sum(); ac=(df['Status']=='A').sum()
    c1,c2,c3 = st.columns(3)
    c1.metric("👥 Total", tot)
    c2.metric("✅ Present", pc, f"{int(pc/tot*100)}%")
    c3.metric("❌ Absent", ac, f"-{ac}", delta_color="inverse")
    v = df.copy()
    if search: v=v[v['Name'].str.contains(search.upper(),na=False)]
    if filt=="Present Only": v=v[v['Status']=='P']
    elif filt=="Absent Only": v=v[v['Status']=='A']
    st.dataframe(v.style.map(_badge,subset=['Status']), use_container_width=True, hide_index=True)
