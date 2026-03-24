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

# --- ១. កំណត់ Page Config & UI Style (ស្អាត និងស្រាលសម្រាប់ Mobile) ---
st.set_page_config(page_title="Reach Maverick AI", layout="wide", page_icon="🎙️")

st.markdown("""
    <style>
    .stButton>button { width: 100%; border-radius: 10px; height: 3em; font-weight: bold; }
    .main-header { text-align: center; color: #FF4B4B; margin-bottom: 20px; }
    div[data-testid="stExpander"] { border: none !important; box-shadow: none !important; }
    /* កែសម្រួលឱ្យមើលលើទូរស័ព្ទស្រួល */
    @media (max-width: 640px) {
        .main-header { font-size: 1.5rem; }
    }
    </style>
    """, unsafe_allow_html=True)

# --- ២. Load Model ទុកក្នុង RAM (ដើម្បីកុំឱ្យចាំយូរពេលចុចបំប្លែង) ---
@st.cache_resource
def get_model():
    return whisper.load_model("tiny") # ប្រើ Tiny គឺលឿនបំផុតសម្រាប់ Mobile

# --- ៣. ប្រព័ន្ធ Login (រក្សាទុកដូចដើម) ---
USER_NAME = "admin"
USER_PASSWORD = "reachzano"

if "logged_in" not in st.session_state: st.session_state.logged_in = False
if "current_step" not in st.session_state: st.session_state.current_step = 0
if "generated_srt" not in st.session_state: st.session_state.generated_srt = ""

def login_system():
    user_val = st_javascript("localStorage.getItem('reach_user');")
    pw_val = st_javascript("localStorage.getItem('reach_pw');")
    active_val = st_javascript("localStorage.getItem('last_active');")
    curr_t = int(time.time())
    
    if active_val and str(user_val) == USER_NAME:
        if (curr_t - int(active_val)) < 600: st.session_state.logged_in = True

    if not st.session_state.logged_in:
        st.markdown("<h1 class='main-header'>🎙️ REACH MAVERICK AI</h1>", unsafe_allow_html=True)
        with st.container(border=True):
            u = st.text_input("Username", value=user_val if user_val else "")
            p = st.text_input("Password", type="password", value=pw_val if pw_val else "")
            if st.button("ចូលប្រើប្រព័ន្ធ", type="primary"):
                if u == USER_NAME and p == USER_PASSWORD:
                    st.session_state.logged_in = True
                    st_javascript(f"localStorage.setItem('last_active', '{curr_t}');")
                    st_javascript(f"localStorage.setItem('reach_user', '{u}');")
                    st_javascript(f"localStorage.setItem('reach_pw', '{p}');")
                    st.rerun()
                else: st.error("លេខសម្ងាត់មិនត្រឹមត្រូវ!")
        st.stop()
login_system()

# --- ៤. Helper Functions (បកប្រែ & តម្រឹមម៉ោង) ---
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

# --- ៥. Sidebar & Navigation ---
with st.sidebar:
    st.title("Reach Maverick")
    mode = st.radio("Step:", ["🎙️ Transcribe", "🎬 Dubbing"], index=st.session_state.current_step)
    st.session_state.current_step = 0 if "Transcribe" in mode else 1
    if st.button("🚪 Logout"):
        st_javascript("localStorage.removeItem('last_active');")
        st.session_state.logged_in = False
        st.rerun()

# --- ៦. STEP 1: TRANSCRIBE (High-Speed) ---
if st.session_state.current_step == 0:
    st.markdown("<h2 class='main-header'>🎙️ Step 1: Video to SRT</h2>", unsafe_allow_html=True)
    v_file = st.file_uploader("ជ្រើសរើសវីដេអូ", type=["mp4", "mp3", "mov", "m4a"])
    if st.button("🚀 ចាប់ផ្ដើមបកប្រែសម្លេង", type="primary"):
        if v_file:
            with open("temp.mp4", "wb") as f: f.write(v_file.getbuffer())
            with st.spinner("⚡ AI កំពុងស្ដាប់..."):
                model = get_model()
                res = model.transcribe("temp.mp4", fp16=False)
            srt_txt = ""
            for i, s in enumerate(res['segments']):
                srt_txt += f"{i+1}\n{format_time(s['start'])} --> {format_time(s['end'])}\n{s['text'].strip()}\n\n"
            st.session_state.generated_srt = srt_txt
            if os.path.exists("temp.mp4"): os.remove("temp.mp4")
            st.rerun()

    if st.session_state.generated_srt:
        st.text_area("SRT Content", st.session_state.generated_srt, height=150)
        if st.button("បន្តទៅ Step 2 ➡️", type="primary"):
            st.session_state.current_step = 1; st.rerun()

# --- ៧. STEP 2: DUBBING (Full Controls) ---
else:
    st.markdown("<h2 class='main-header'>🎬 Step 2: AI Dubbing</h2>", unsafe_allow_html=True)
    if not st.session_state.generated_srt:
        st.warning("សូមបកប្រែសម្លេងនៅ Step 1 សិន!"); st.button("⬅️ ត្រឡប់ក្រោយ", on_click=lambda: setattr(st.session_state, 'current_step', 0))
    else:
        if 'data' not in st.session_state:
            if st.button("📥 បកប្រែអត្ថបទជាខ្មែរ", type="primary"):
                subs = list(srt.parse(st.session_state.generated_srt))
                with st.spinner("⏳ កំពុងបកប្រែ..."):
                    km_list = GoogleTranslator(source='auto', target='km').translate_batch([s.content for s in subs])
                st.session_state.data = [{"ID": i, "Select": False, "English": subs[i].content, "Khmer_Text": simplify_khmer(km_list[i]), "Voice": "Male", "Start": subs[i].start, "End": subs[i].end} for i in range(len(subs))]
                st.rerun()

        if st.session_state.get('data'):
            df = pd.DataFrame(st.session_state.data)
            edit_df = st.data_editor(df, use_container_width=True, hide_index=True, 
                column_config={"Select": st.column_config.CheckboxColumn("✅"), "Khmer_Text": st.column_config.TextColumn("អត្ថបទខ្មែរ", width="large"), "Voice": st.column_config.SelectboxColumn("ភេទ", options=["Male", "Female"]), "ID":None, "Start":None, "End":None, "English":None})
            
            # Quick Buttons (Mobile Friendly)
            c1, c2 = st.columns(2); c3, c4 = st.columns(2)
            if c1.button("🌸 ស្រីទាំងអស់"):
                for x in st.session_state.data: x['Voice'] = "Female"; st.rerun()
            if c2.button("💎 ប្រុសទាំងអស់"):
                for x in st.session_state.data: x['Voice'] = "Male"; st.rerun()
            if c3.button("👩‍🦰 Tick -> ស្រី"):
                for i, r in edit_df.iterrows():
                    if r['Select']: st.session_state.data[i]['Voice'] = "Female"; st.rerun()
            if c4.button("👨‍🦱 Tick -> ប្រុស"):
                for i, r in edit_df.iterrows():
                    if r['Select']: st.session_state.data[i]['Voice'] = "Male"; st.rerun()

            st.divider()
            spd_val = st.slider("ល្បឿននិយាយ (%)", -50, 50, 0)
            bgm = st.file_uploader("ភ្លេង BGM (បើមាន)", type=["mp3"])
            
            if st.button("🚀 START TURBO DUBBING", type="primary"):
                st.session_state.data = edit_df.to_dict('records')
                async def run_now():
                    return await asyncio.gather(*[fetch_tts(r, i, spd_val) for i, r in enumerate(st.session_state.data)])
                with st.spinner("🎙️ កំពុងផលិតសម្លេងរលូន..."):
                    f_list = asyncio.run(run_now())
                    combined = AudioSegment.silent(duration=0)
                    curr_ms = 0
                    for i, r in enumerate(st.session_state.data):
                        s_ms, e_ms = int(r['Start'].total_seconds()*1000), int(r['End'].total_seconds()*1000)
                        seg = AudioSegment.from_file(f_list[i]).strip_silence()
                        d = max(1, e_ms - s_ms)
                        if len(seg) > (d + 300): seg = speedup(seg, playback_speed=min(len(seg)/d, 1.4), chunk_size=150, crossfade=25)
                        if s_ms > curr_ms: combined += AudioSegment.silent(duration=s_ms - curr_ms); combined += seg
                        else: combined = combined.append(seg, crossfade=100)
                        curr_ms = len(combined); os.remove(f_list[i])
                    if bgm:
                        b_seg = AudioSegment.from_file(bgm) - 25
                        combined = combined.overlay(b_seg * (int(len(combined)/len(b_seg)) + 1))
                    combined.export("final.mp3", format="mp3")
                    with open("final.mp3", "rb") as f: st.session_state.audio_bytes = f.read()
                st.success("ផលិតរួចរាល់!")

            if st.session_state.get('audio_bytes'):
                st.audio(st.session_state.audio_bytes)
                st.download_button("📥 ទាញយក MP3", st.session_state.audio_bytes, "reach_maverick.mp3", type="primary")

        st.button("⬅️ ត្រឡប់ទៅ Step 1", on_click=lambda: setattr(st.session_state, 'current_step', 0))
