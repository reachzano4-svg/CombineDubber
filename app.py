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

# --- ១. កំណត់ Page Config ---
st.set_page_config(page_title="Reach AI Pro", layout="wide")

# --- ២. ប្រព័ន្ធ Login (ចងចាំ Password & Timeout 3mn) ---
USER_NAME = "admin"
USER_PASSWORD = "reachzano"

def login():
    # ព្យាយាមទាញយកទិន្នន័យពី Browser Storage
    stored_user = st_javascript("localStorage.getItem('reach_user');")
    stored_pw = st_javascript("localStorage.getItem('reach_pw');")
    last_active = st_javascript("localStorage.getItem('last_active');")
    current_time = int(time.time())
    
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "current_step" not in st.session_state:
        st.session_state.current_step = 0

    # ឆែក Timeout 3 នាទី (180 វិនាទី)
    if last_active and str(stored_user) == USER_NAME:
        if (current_time - int(last_active)) > 180:
            st.session_state.logged_in = False
        else:
            st.session_state.logged_in = True
    
    if not st.session_state.logged_in:
        st.markdown("<h2 style='text-align: center;'>🔐 Login Reach AI</h2>", unsafe_allow_html=True)
        _, col2, _ = st.columns([1, 1.5, 1])
        with col2:
            user = st.text_input("Username", value=stored_user if stored_user else "")
            pw = st.text_input("Password", type="password", value=stored_pw if stored_pw else "")
            remember = st.checkbox("ចងចាំលេខសម្ងាត់")
            if st.button("ចូលប្រើ", type="primary", use_container_width=True):
                if user == USER_NAME and pw == USER_PASSWORD:
                    st.session_state.logged_in = True
                    st_javascript(f"localStorage.setItem('last_active', '{current_time}');")
                    if remember:
                        st_javascript(f"localStorage.setItem('reach_user', '{user}');")
                        st_javascript(f"localStorage.setItem('reach_pw', '{pw}');")
                    st.rerun()
                else:
                    st.error("ខុសលេខសម្ងាត់!")
        st.stop()
    else:
        # Update ពេលវេលា Active រហូត
        st_javascript(f"localStorage.setItem('last_active', '{current_time}');")

login()

# --- ៣. Helper Functions ---
def format_time(seconds):
    td = datetime.timedelta(seconds=seconds)
    total_sec = int(td.total_seconds())
    milis = int((td.total_seconds() - total_sec) * 1000)
    return f"{total_sec // 3600:02}:{(total_sec % 3600) // 60:02}:{total_sec % 60:02},{milis:03}"

def simplify_khmer(text):
    if not text: return ""
    replaces = {"តើ(.*)មែនទេ": r"\1មែនអត់?", "របស់អ្នក": "ឯង", "បាទ": "បាទបង", "ចាស": "ចា៎", "ខ្ញុំ": "ខ្ញុំ"}
    for p, r in replaces.items(): text = re.sub(p, r, text)
    return text.strip()

async def process_audio(data, base_speed, status, progress):
    combined = AudioSegment.silent(duration=0)
    current_ms = 0
    for i, row in enumerate(data):
        progress.progress((i + 1) / len(data))
        status.write(f"🎙️ ផលិតឃ្លាទី {i+1}...")
        text = str(row['Khmer_Text']).strip()
        start_ms = int(row['Start'].total_seconds() * 1000)
        end_ms = int(row['End'].total_seconds() * 1000)
        
        if start_ms > current_ms:
            combined += AudioSegment.silent(duration=start_ms - current_ms)
            current_ms = start_ms
            
        voice = "km-KH-SreymomNeural" if row['Voice'] == "Female" else "km-KH-PisethNeural"
        tmp = f"temp_{i}.mp3"
        await edge_tts.Communicate(text, voice, rate=f"{base_speed:+}%").save(tmp)
        
        if os.path.exists(tmp):
            seg = AudioSegment.from_file(tmp)
            duration_srt = end_ms - start_ms
            if len(seg) > (duration_srt + 500):
                seg = speedup(seg, playback_speed=min(len(seg)/duration_srt, 1.4), chunk_size=150, crossfade=25)
            combined += seg
            current_ms += len(seg)
            os.remove(tmp)
    return combined

# --- ៤. Navigation Logic ---
step_options = ["Step 1: Transcribe", "Step 2: Dubbing"]
choice = st.sidebar.radio("ជំហានការងារ", step_options, index=st.session_state.current_step)

if choice == step_options[0]: st.session_state.current_step = 0
else: st.session_state.current_step = 1

if st.sidebar.button("🚪 Logout"):
    st_javascript("localStorage.removeItem('last_active');")
    st.session_state.logged_in = False
    st.rerun()

# --- ៥. STEP 1: TRANSCRIBE ---
if st.session_state.current_step == 0:
    st.title("🎙️ Step 1: Video to SRT")
    video_file = st.file_uploader("Upload Video/Audio", type=["mp4", "mp3", "mov", "m4a"])
    
    if st.button("🚀 ចាប់ផ្ដើមបំប្លែង", type="primary"):
        if video_file:
            with st.spinner("កំពុងស្តាប់ (ប្រើ Model Tiny ដើម្បីល្បឿន)..."):
                with open("temp.mp4", "wb") as f: f.write(video_file.getbuffer())
                model = whisper.load_model("tiny")
                res = model.transcribe("temp.mp4")
                srt_out = ""
                for i, s in enumerate(res['segments']):
                    srt_out += f"{i+1}\n{format_time(s['start'])} --> {format_time(s['end'])}\n{s['text'].strip()}\n\n"
                st.session_state.generated_srt = srt_out
                if os.path.exists("temp.mp4"): os.remove("temp.mp4")
                st.success("បំប្លែងរួចរាល់!")

    if st.session_state.get('generated_srt'):
        st.text_area("លទ្ធផល SRT", st.session_state.generated_srt, height=250)
        st.divider()
        col_reset, col_next = st.columns([5, 1])
        with col_reset:
            if st.button("🗑️ Reset Data"): 
                st.session_state.generated_srt = ""
                if 'data' in st.session_state: del st.session_state.data
                st.rerun()
        with col_next:
            if st.button("បន្តទៅមុខ ➡️", type="primary", use_container_width=True):
                st.session_state.current_step = 1
                st.rerun()

# --- ៦. STEP 2: DUBBING ---
else:
    st.title("🎬 Step 2: AI Dubbing & Voice")
    srt_input = st.session_state.get('generated_srt', "")
    
    if not srt_input:
        st.warning("⚠️ សូមធ្វើ Step 1 សិន!")
        if st.button("⬅️ ទៅកាន់ Step 1"):
            st.session_state.current_step = 0
            st.rerun()
    else:
        if 'data' not in st.session_state:
            if st.button("📥 បកប្រែអត្ថបទពី Step 1", type="primary"):
                subs = list(srt.parse(srt_input))
                tr_en = GoogleTranslator(source='auto', target='en')
                tr_km = GoogleTranslator(source='en', target='km')
                data = []
                p = st.empty()
                for i, s in enumerate(subs):
                    p.write(f"បកប្រែឃ្លាទី {i+1}...")
                    en = tr_en.translate(s.content)
                    km = simplify_khmer(tr_km.translate(en))
                    data.append({"ID": i, "Select": False, "English": en, "Khmer_Text": km, "Voice": "Male", "Start": s.start, "End": s.end})
                st.session_state.data = data
                st.rerun()

        if st.session_state.get('data'):
            df = pd.DataFrame(st.session_state.data)
            tab_edit, tab_setting, tab_process = st.tabs(["📝 កែអត្ថបទ & រើសភេទ", "⚙️ កំណត់សម្លេង", "🎵 ផលិត MP3"])
            
            with tab_edit:
                edited_df = st.data_editor(df, use_container_width=True, hide_index=True,
                    column_config={
                        "Select": st.column_config.CheckboxColumn("រើស", default=False),
                        "Khmer_Text": st.column_config.TextColumn("អត្ថបទខ្មែរ", width="large"),
                        "Voice": st.column_config.SelectboxColumn("ភេទ", options=["Male", "Female"]),
                        "ID":None, "Start":None, "End":None, "English": None
                    })
                
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    if st.button("🌸 ស្រីទាំងអស់"):
                        for item in st.session_state.data: item['Voice'] = "Female"
                        st.rerun()
                with c2:
                    if st.button("💎 ប្រុសទាំងអស់"):
                        for item in st.session_state.data: item['Voice'] = "Male"
                        st.rerun()
                with c3:
                    if st.button("👩‍🦰 Tick -> ស្រី"):
                        for item in st.session_state.data:
                            if edited_df.loc[edited_df['ID'] == item['ID'], 'Select'].values[0]: item['Voice'] = "Female"
                        st.rerun()
                with c4:
                    if st.button("👨‍🦱 Tick -> ប្រុស"):
                        for item in st.session_state.data:
                            if edited_df.loc[edited_df['ID'] == item['ID'], 'Select'].values[0]: item['Voice'] = "Male"
                        st.rerun()
                
                if st.button("💾 រក្សាទុកការកែសម្រួល", use_container_width=True):
                    st.session_state.data = edited_df.to_dict('records')
                    st.success("Saved!")

            with tab_setting:
                speed = st.slider("ល្បឿននិយាយ (%)", -50, 50, 0)
                bgm_file = st.file_uploader("ថែមភ្លេង BGM", type=["mp3"])
                bgm_vol = st.slider("កម្រិតសម្លេង BGM", 0, 100, 20)
            
            with tab_process:
                if st.button("🚀 START DUBBING", type="primary"):
                    stat, pb = st.empty(), st.progress(0)
                    res_audio = asyncio.run(process_audio(st.session_state.data, speed, stat, pb))
                    if bgm_file:
                        bgm = AudioSegment.from_file(bgm_file) - (60 - (bgm_vol * 0.6))
                        res_audio = res_audio.overlay(bgm * (int(len(res_audio)/len(bgm)) + 1))
                    res_audio.export("final.mp3", format="mp3")
                    with open("final.mp3", "rb") as f: st.session_state.audio_bytes = f.read()
                    st.success("ផលិតរួចរាល់!")
                
                if st.session_state.get('audio_bytes'):
                    st.audio(st.session_state.audio_bytes)
                    st.download_button("📥 ទាញយក MP3", st.session_state.audio_bytes, "reach_ai_dub.mp3")

        st.divider()
        if st.button("⬅️ ត្រលប់ក្រោយ"):
            st.session_state.current_step = 0
            st.rerun()
