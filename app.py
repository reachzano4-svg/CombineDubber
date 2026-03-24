try:
    import audioop
except ImportError:
    import audioop_lts as audioop
    import sys
    sys.modules['audioop'] = audioop

import streamlit as st
import whisper
import datetime
import asyncio, edge_tts, srt, os, re, pandas as pd, time
from pydub import AudioSegment
from pydub.effects import speedup
from deep_translator import GoogleTranslator
from streamlit_javascript import st_javascript

# --- ១. កំណត់ Page Config & Gold Theme ---
st.set_page_config(page_title="Reach Maverick AI", layout="wide", page_icon="🎙️")

st.markdown("""
    <style>
    .stApp { background-color: #0E1117; }
    .gold-text {
        text-align: center;
        background: linear-gradient(90deg, #D4AF37, #F9E27E, #D4AF37);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-family: 'Kantumruy Pro', sans-serif;
        font-weight: 800;
        margin-bottom: 10px;
    }
    .stButton>button {
        background: linear-gradient(145deg, #D4AF37, #B8860B) !important;
        color: black !important;
        font-weight: bold !important;
        border-radius: 12px !important;
        height: 3.5em !important;
    }
    section[data-testid="stSidebar"] { background-color: #000000; border-right: 1px solid #D4AF37; }
    </style>
    """, unsafe_allow_html=True)

# --- ២. Engine Loading ---
@st.cache_resource
def load_whisper_engine():
    return whisper.load_model("tiny")

# --- ៣. Login System ---
USER_NAME = "admin"
USER_PASSWORD = "reachzano"

if "logged_in" not in st.session_state: st.session_state.logged_in = False
if "current_step" not in st.session_state: st.session_state.current_step = 0
if "generated_srt" not in st.session_state: st.session_state.generated_srt = ""

def login_system():
    u_val = st_javascript("localStorage.getItem('reach_user');")
    p_val = st_javascript("localStorage.getItem('reach_pw');")
    act_val = st_javascript("localStorage.getItem('last_active');")
    now_t = int(time.time())
    if act_val and str(u_val) == USER_NAME:
        if (now_t - int(act_val)) < 3600: st.session_state.logged_in = True
    if not st.session_state.logged_in:
        st.markdown("<h1 class='gold-text'>🎙️ REACH MAVERICK AI</h1>", unsafe_allow_html=True)
        with st.container(border=True):
            u = st.text_input("👤 Username", value=u_val if u_val else "")
            p = st.text_input("🔑 Password", type="password", value=p_val if p_val else "")
            if st.button("SIGN IN"):
                if u == USER_NAME and p == USER_PASSWORD:
                    st.session_state.logged_in = True
                    st_javascript(f"localStorage.setItem('last_active', '{now_t}');")
                    st_javascript(f"localStorage.setItem('reach_user', '{u}');")
                    st_javascript(f"localStorage.setItem('reach_pw', '{p}');")
                    st.rerun()
                else: st.error("លេខសម្ងាត់មិនត្រឹមត្រូវ!")
        st.stop()
login_system()

# --- ៤. Helpers ---
def format_time(seconds):
    td = datetime.timedelta(seconds=seconds)
    total_sec = int(td.total_seconds())
    milis = int((td.total_seconds() - total_sec) * 1000)
    return f"{total_sec // 3600:02}:{(total_sec % 3600) // 60:02}:{total_sec % 60:02},{milis:03}"

async def fetch_tts(row, idx, spd):
    v = "km-KH-SreymomNeural" if row['Voice'] == "Female" else "km-KH-PisethNeural"
    fn = f"s_{idx}.mp3"
    await edge_tts.Communicate(str(row['Khmer_Text']), v, rate=f"{spd:+}%").save(fn)
    return fn

# --- ៥. STEP 1: TRANSCRIBE & AUTO-MERGE ---
if st.session_state.current_step == 0:
    st.markdown("<h2 class='gold-text'>🎙️ STEP 1: VIDEO TO SRT (AUTO-MERGE)</h2>", unsafe_allow_html=True)
    f = st.file_uploader("Upload Video/Audio", type=["mp4", "mp3", "mov", "m4a"])
    if st.button("🚀 START FAST TRANSCRIBE"):
        if f:
            with open("temp_raw", "wb") as file: file.write(f.getbuffer())
            with st.spinner("⚡ កំពុងបំប្លែង និងផ្គួបឃ្លាដែលនៅជិតគ្នា..."):
                model = load_whisper_engine()
                res = model.transcribe("temp_raw", fp16=False)
                
                # Logic: ផ្គួបឃ្លាណាដែលនៅក្បែរគ្នា (Gap < 0.6s) ដើម្បីឱ្យ AI អានរលូន
                segs = res['segments']
                merged = []
                if segs:
                    curr = segs[0]
                    for i in range(1, len(segs)):
                        nxt = segs[i]
                        gap = nxt['start'] - curr['end']
                        if gap < 0.6: 
                            curr['text'] += " " + nxt['text']
                            curr['end'] = nxt['end']
                        else:
                            merged.append(curr)
                            curr = nxt
                    merged.append(curr)

                srt_txt = ""
                for i, s in enumerate(merged):
                    srt_txt += f"{i+1}\n{format_time(s['start'])} --> {format_time(s['end'])}\n{s['text'].strip()}\n\n"
                st.session_state.generated_srt = srt_txt
                if os.path.exists("temp_raw"): os.remove("temp_raw")
                st.rerun()

    if st.session_state.generated_srt:
        st.text_area("SRT Result (Merged)", st.session_state.generated_srt, height=250)
        if st.button("បន្តទៅ Dubbing ➡️"):
            st.session_state.current_step = 1; st.rerun()

# --- ៦. STEP 2: DUBBING (PERFECT SYNC LOGIC) ---
else:
    st.markdown("<h2 class='gold-text'>🎬 STEP 2: AI GOLD DUBBING (SYNCED)</h2>", unsafe_allow_html=True)
    if 'data' not in st.session_state:
        if st.button("📥 បកប្រែជាភាសាខ្មែរ"):
            subs = list(srt.parse(st.session_state.generated_srt))
            with st.spinner("⏳ កំពុងបកប្រែ..."):
                km_list = GoogleTranslator(source='auto', target='km').translate_batch([s.content for s in subs])
            st.session_state.data = [{"ID": i, "Select": False, "Khmer_Text": km_list[i], "Voice": "Male", "Start": subs[i].start, "End": subs[i].end} for i in range(len(subs))]
            st.rerun()

    if st.session_state.get('data'):
        df = pd.DataFrame(st.session_state.data)
        edit_df = st.data_editor(df, use_container_width=True, hide_index=True, 
            column_config={"Khmer_Text": st.column_config.TextColumn("អត្ថបទខ្មែរ", width="large"), "Voice": st.column_config.SelectboxColumn("ភេទ", options=["Male", "Female"])})
        
        spd_val = st.slider("ល្បឿននិយាយសរុប (%)", -50, 50, 0)
        
        if st.button("🚀 ផលិតសម្លេង Dubbing (ត្រូវនាទី ១០០%)", type="primary"):
            st.session_state.data = edit_df.to_dict('records')
            async def run_now():
                return await asyncio.gather(*[fetch_tts(r, i, spd_val) for i, r in enumerate(st.session_state.data)])
            
            with st.spinner("🎙️ កំពុង Sync សម្លេងឱ្យត្រូវ Timeline..."):
                f_list = asyncio.run(run_now())
                
                # បង្កើត Timeline សរុប
                total_dur = int(st.session_state.data[-1]['End'].total_seconds() * 1000) + 1500
                final_audio = AudioSegment.silent(duration=total_dur, frame_rate=24000)
                
                for i, r in enumerate(st.session_state.data):
                    s_ms = int(r['Start'].total_seconds() * 1000)
                    e_ms = int(r['End'].total_seconds() * 1000)
                    limit = e_ms - s_ms
                    
                    if os.path.exists(f_list[i]):
                        seg = AudioSegment.from_file(f_list[i]).set_frame_rate(24000)
                        
                        # បើអានវែងជាងនាទីក្នុងរឿង ត្រូវបង្កើនល្បឿនអូតូ
                        if len(seg) > limit:
                            seg = speedup(seg, playback_speed=min(len(seg)/limit, 1.4), chunk_size=150, crossfade=25)
                            seg = seg[:limit] # កាត់តម្រឹមឱ្យល្មមបេះបិទ
                        
                        # ដាក់សម្លេងឱ្យចំចំនុច Start ជានិច្ច (ទោះឃ្លាមុនវែងក៏មិនប៉ះពាល់)
                        final_audio = final_audio.overlay(seg, position=s_ms)
                        os.remove(f_list[i])
                
                final_audio.export("final_reach.mp3", format="mp3")
                with open("final_reach.mp3", "rb") as file: 
                    st.session_state.audio_bytes = file.read()
            st.balloons()

        if st.session_state.get('audio_bytes'):
            st.audio(st.session_state.audio_bytes)
            st.download_button("📥 DOWNLOAD DUBBING", st.session_state.audio_bytes, "reach_maverick_synced.mp3")

    st.button("⬅️ BACK", on_click=lambda: setattr(st.session_state, 'current_step', 0))
