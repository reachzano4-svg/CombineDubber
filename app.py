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

# --- ១. កំណត់ Page Config & Custom Gold-Black Theme ---
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
        border: none !important;
        border-radius: 12px !important;
        font-weight: bold !important;
        height: 3.5em !important;
        width: 100% !important;
        box-shadow: 0 4px 15px rgba(212, 175, 55, 0.2);
    }
    section[data-testid="stSidebar"] { background-color: #000000; border-right: 1px solid #D4AF37; }
    div[data-testid="stExpander"] { border: 1px solid #D4AF37 !important; border-radius: 10px; }
    /* Table styling */
    .stDataEditor { border: 1px solid #444; }
    </style>
    """, unsafe_allow_html=True)

# --- ២. Turbo Engine Loading (Cache ទុកក្នុង RAM) ---
@st.cache_resource
def load_whisper_engine():
    return whisper.load_model("tiny")

# --- ៣. ប្រព័ន្ធ Login ---
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
            if st.button("SIGN IN TO SYSTEM"):
                if u == USER_NAME and p == USER_PASSWORD:
                    st.session_state.logged_in = True
                    st_javascript(f"localStorage.setItem('last_active', '{now_t}');")
                    st_javascript(f"localStorage.setItem('reach_user', '{u}');")
                    st_javascript(f"localStorage.setItem('reach_pw', '{p}');")
                    st.rerun()
                else: st.error("លេខសម្ងាត់មិនត្រឹមត្រូវ!")
        st.stop()
    else:
        st_javascript(f"localStorage.setItem('last_active', '{now_t}');")

login_system()

# --- ៤. Helper Functions ---
def format_time(seconds):
    td = datetime.timedelta(seconds=seconds)
    total_sec = int(td.total_seconds())
    milis = int((td.total_seconds() - total_sec) * 1000)
    return f"{total_sec // 3600:02}:{(total_sec % 3600) // 60:02}:{total_sec % 60:02},{milis:03}"

def simplify_khmer(text):
    if not text: return ""
    reps = {"តើ(.*)មែនទេ": r"\1មែនអត់?", "របស់អ្នក": "ឯង", "បាទ": "បាទបង", "ចាស": "ចា៎", "អរគុណ": "អរគុណបង"}
    for p, r in reps.items(): text = re.sub(p, r, text)
    return text.strip()

async def fetch_tts(row, idx, spd):
    v = "km-KH-SreymomNeural" if row['Voice'] == "Female" else "km-KH-PisethNeural"
    fn = f"s_{idx}.mp3"
    await edge_tts.Communicate(str(row['Khmer_Text']), v, rate=f"{spd:+}%").save(fn)
    return fn

# --- ៥. Sidebar ---
with st.sidebar:
    st.markdown("<h2 style='color: #D4AF37;'>MAVERICK AI</h2>", unsafe_allow_html=True)
    st.info(f"👤 Admin: **Reach**")
    mode = st.radio("Step:", ["🎙️ Transcribe (Turbo)", "🎬 Dubbing (Gold)"], index=st.session_state.current_step)
    st.session_state.current_step = 0 if "Transcribe" in mode else 1
    if st.button("🚪 LOGOUT"):
        st_javascript("localStorage.removeItem('last_active');")
        st.session_state.logged_in = False
        st.rerun()

# --- ៦. STEP 1: TRANSCRIBE (Ultra-Fast for 10mn+) ---
if st.session_state.current_step == 0:
    st.markdown("<h2 class='gold-text'>🎙️ STEP 1: VIDEO TO SRT (TURBO)</h2>", unsafe_allow_html=True)
    with st.container(border=True):
        f = st.file_uploader("Upload Video/Audio (Support 10mn+)", type=["mp4", "mp3", "mov", "m4a"])
        if st.button("🚀 START SUPER FAST TRANSCRIBE"):
            if f:
                with open("temp_raw", "wb") as file: file.write(f.getbuffer())
                start_t = time.time()
                with st.spinner("⚡ កំពុងរៀបចំសម្លេង និងបំប្លែងយ៉ាងលឿន..."):
                    audio = AudioSegment.from_file("temp_raw")
                    audio = audio.set_frame_rate(16000).set_channels(1)
                    audio.export("temp_low.wav", format="wav")
                    
                    model = load_whisper_engine()
                    res = model.transcribe("temp_low.wav", fp16=False, beam_size=1)
                
                srt_txt = ""
                for i, s in enumerate(res['segments']):
                    srt_txt += f"{i+1}\n{format_time(s['start'])} --> {format_time(s['end'])}\n{s['text'].strip()}\n\n"
                
                st.session_state.generated_srt = srt_txt
                for tmp in ["temp_raw", "temp_low.wav"]:
                    if os.path.exists(tmp): os.remove(tmp)
                
                st.success(f"✅ រួចរាល់! ចំណាយពេល: {round(time.time() - start_t, 1)} វិនាទី")
                st.rerun()

    if st.session_state.generated_srt:
        st.text_area("លទ្ធផល SRT", st.session_state.generated_srt, height=200)
        if st.button("បន្តទៅ Step 2 ➡️"):
            st.session_state.current_step = 1; st.rerun()

# --- ៧. STEP 2: DUBBING (Safe Audio Stitching) ---
else:
    st.markdown("<h2 class='gold-text'>🎬 STEP 2: AI GOLD DUBBING</h2>", unsafe_allow_html=True)
    if not st.session_state.generated_srt:
        st.warning("សូមបកប្រែនៅ Step 1 សិន!"); st.button("⬅️ BACK", on_click=lambda: setattr(st.session_state, 'current_step', 0))
    else:
        if 'data' not in st.session_state:
            if st.button("📥 TRANSLATE TO KHMER", type="primary"):
                subs = list(srt.parse(st.session_state.generated_srt))
                with st.spinner("⏳ កំពុងបកប្រែ..."):
                    km_list = GoogleTranslator(source='auto', target='km').translate_batch([s.content for s in subs])
                st.session_state.data = [{"ID": i, "Select": False, "English": subs[i].content, "Khmer_Text": simplify_khmer(km_list[i]), "Voice": "Male", "Start": subs[i].start, "End": subs[i].end} for i in range(len(subs))]
                st.rerun()

        if st.session_state.get('data'):
            df = pd.DataFrame(st.session_state.data)
            edit_df = st.data_editor(df, use_container_width=True, hide_index=True, 
                column_config={"Select": st.column_config.CheckboxColumn("✅"), "Khmer_Text": st.column_config.TextColumn("អត្ថបទខ្មែរ", width="large"), "Voice": st.column_config.SelectboxColumn("ភេទ", options=["Male", "Female"]), "ID":None, "Start":None, "End":None, "English":None})
            
            c1, c2, c3, c4 = st.columns(4)
            if c1.button("🌸 All Female"):
                for x in st.session_state.data: x['Voice'] = "Female"; st.rerun()
            if c2.button("💎 All Male"):
                for x in st.session_state.data: x['Voice'] = "Male"; st.rerun()
            if c3.button("👩‍🦰 Tick->F"):
                for i, r in edit_df.iterrows():
                    if r['Select']: st.session_state.data[i]['Voice'] = "Female"; st.rerun()
            if c4.button("👨‍🦱 Tick->M"):
                for i, r in edit_df.iterrows():
                    if r['Select']: st.session_state.data[i]['Voice'] = "Male"; st.rerun()

            st.divider()
            with st.expander("⚙️ Settings (Speed & BGM)"):
                spd_val = st.slider("ល្បឿននិយាយ (%)", -50, 50, 0)
                bgm = st.file_uploader("ដាក់ភ្លេង Background", type=["mp3"])
            
            if st.button("🚀 PRODUCE DUBBING MP3", type="primary"):
                st.session_state.data = edit_df.to_dict('records')
                async def run_now():
                    return await asyncio.gather(*[fetch_tts(r, i, spd_val) for i, r in enumerate(st.session_state.data)])
                
                with st.spinner("🎙️ កំពុងផលិតសម្លេងរលូន..."):
                    f_list = asyncio.run(run_now())
                    combined = AudioSegment.silent(duration=0)
                    curr_ms = 0
                    
                    for i, r in enumerate(st.session_state.data):
                        s_ms, e_ms = int(r['Start'].total_seconds()*1000), int(r['End'].total_seconds()*1000)
                        
                        # ពិនិត្យមើលវត្តមាន File សម្លេង
                        if os.path.exists(f_list[i]):
                            seg = AudioSegment.from_file(f_list[i]).strip_silence()
                            
                            # បើ Audio ខ្លីពេក (ការពារ Error Crossfade)
                            if len(seg) < 10:
                                seg = AudioSegment.silent(duration=10)
                                
                            dur = max(1, e_ms - s_ms)
                            if len(seg) > (dur + 300):
                                seg = speedup(seg, playback_speed=min(len(seg)/dur, 1.4), chunk_size=150, crossfade=25)
                            
                            # សរសេរសម្លេងចូល Timeline (Safe Logic)
                            if s_ms > curr_ms:
                                combined += AudioSegment.silent(duration=s_ms - curr_ms)
                                combined += seg
                            else:
                                # បើ combined វែងជាង 100ms ទើបអនុញ្ញាតឱ្យប្រើ Crossfade
                                if len(combined) > 100:
                                    combined = combined.append(seg, crossfade=100)
                                else:
                                    combined += seg
                                    
                            curr_ms = len(combined)
                            os.remove(f_list[i])
                    
                    if bgm:
                        b_seg = AudioSegment.from_file(bgm) - 25
                        combined = combined.overlay(b_seg * (int(len(combined)/len(b_seg)) + 1))
                    
                    combined.export("final.mp3", format="mp3")
                    with open("final.mp3", "rb") as file: 
                        st.session_state.audio_bytes = file.read()
                st.balloons()

            if st.session_state.get('audio_bytes'):
                st.audio(st.session_state.audio_bytes)
                st.download_button("📥 DOWNLOAD FINAL MP3", st.session_state.audio_bytes, "reach_maverick.mp3")

        st.button("⬅️ BACK TO STEP 1", on_click=lambda: setattr(st.session_state, 'current_step', 0))
