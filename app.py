import os
import time
import datetime
import asyncio
import edge_tts
import srt
import pandas as pd
import google.generativeai as genai
import streamlit as st
from pydub import AudioSegment
from pydub.effects import speedup
from streamlit_javascript import st_javascript

# --- ១. កំណត់ Page Config & API ---
st.set_page_config(page_title="Reach AI Maverick Pro", layout="wide")

# កំណត់ API Key របស់បងត្រង់នេះ
API_KEY = "AIzaSyA4cqoTPWFsavOCEra_0aTJ-r7HciPnBto"
genai.configure(api_key=API_KEY)

# --- ២. ប្រព័ន្ធ Login (រក្សាទុកតាមសំណើបង) ---
USER_NAME = "admin"
USER_PASSWORD = "reachzano"

def login():
    stored_user = st_javascript("localStorage.getItem('reach_user');")
    stored_pw = st_javascript("localStorage.getItem('reach_pw');")
    last_active = st_javascript("localStorage.getItem('last_active');")
    current_time = int(time.time())
    timeout_seconds = 180 

    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    if last_active and stored_user == USER_NAME:
        elapsed = current_time - int(last_active)
        if elapsed > timeout_seconds:
            st.session_state.logged_in = False
        else:
            st.session_state.logged_in = True
    
    if not st.session_state.logged_in:
        st.markdown("<h2 style='text-align: center;'>🔐 ចូលប្រើប្រាស់ Reach AI</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col2:
            user = st.text_input("Username", value=stored_user if stored_user else "")
            pw = st.text_input("Password", type="password", value=stored_pw if stored_pw else "")
            remember = st.checkbox("ចងចាំលេខសម្ងាត់ (Remember Me)")
            if st.button("ចូលប្រើ", type="primary", use_container_width=True):
                if user == USER_NAME and pw == USER_PASSWORD:
                    st.session_state.logged_in = True
                    st.session_state.current_step = 0
                    st_javascript(f"localStorage.setItem('last_active', '{current_time}');")
                    if remember:
                        st_javascript(f"localStorage.setItem('reach_user', '{user}');")
                        st_javascript(f"localStorage.setItem('reach_pw', '{pw}');")
                    st.rerun()
                else:
                    st.error("ខុសឈ្មោះ ឬលេខសម្ងាត់!")
        st.stop()
    else:
        st_javascript(f"localStorage.setItem('last_active', '{current_time}');")

login()

# --- ៣. Helper Functions (Gemini Logic) ---
def get_working_model():
    # ប្រើ Flash 1.5 ព្រោះវាលឿនបំផុតសម្រាប់ Streaming Audio
    return "models/gemini-1.5-flash"

def simplify_khmer(text):
    if not text: return ""
    replaces = {"តើ(.*)មែនទេ": r"\1មែនអត់?", "របស់អ្នក": "ឯង", "បាទ": "បាទបង", "ចាស": "ចា៎"}
    for p, r in replaces.items(): text = re.sub(p, r, text)
    return text.strip()

async def process_audio_dubbing(data, base_speed, status, progress):
    combined = AudioSegment.silent(duration=0)
    current_ms = 0
    for i, row in enumerate(data):
        progress.progress((i + 1) / len(data))
        status.write(f"🎙️ ផលិតសម្លេងឃ្លាទី {i+1}...")
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
            duration_limit = end_ms - start_ms
            if len(seg) > (duration_limit + 500):
                seg = speedup(seg, playback_speed=min(len(seg)/duration_limit, 1.4))
            combined += seg
            current_ms += len(seg)
            os.remove(tmp)
    return combined

# --- ៤. Main UI Logic ---
if 'current_step' not in st.session_state: st.session_state.current_step = 0

step_options = ["🎙️ Transcribe & Translate", "🎬 AI Dubbing"]
selected_step = st.sidebar.radio("ជំហានការងារ", step_options, index=st.session_state.current_step)
st.session_state.current_step = 0 if selected_step == step_options[0] else 1

# --- ទំព័រទី ១: TRANSCRIBE & TRANSLATE (ជាមួយ Gemini) ---
if st.session_state.current_step == 0:
    st.title("🎙️ Step 1: Gemini Audio Intelligence")
    video_file = st.file_uploader("ជ្រើសរើសវីដេអូ ឬសម្លេង", type=["mp4", "mp3", "mov", "m4a"])
    
    if st.button("🚀 ចាប់ផ្ដើមបំប្លែងជាមួយ Gemini", type="primary"):
        if video_file:
            with st.spinner("Gemini កំពុងស្តាប់ និងបកប្រែ..."):
                with open("temp_input", "wb") as f: f.write(video_file.getbuffer())
                
                # បង្ហោះទៅ Google Server
                gemini_file = genai.upload_file(path="temp_input")
                while gemini_file.state.name == "PROCESSING":
                    time.sleep(2)
                    gemini_file = genai.get_file(gemini_file.name)
                
                model = genai.GenerativeModel(model_name=get_working_model())
                
                # Prompt ពិសេសបង្រួម Step: Transcribe + Translate ជាភាសាខ្មែរែក្នុងពេលតែមួយ
                prompt = (
                    "Transcribe this audio into SRT format. "
                    "Crucial: Translate everything into natural, conversational Khmer. "
                    "Use appropriate pronouns like 'បង', 'អូន' for drama context. "
                    "Output ONLY the raw SRT content."
                )
                
                response = model.generate_content([prompt, gemini_file])
                st.session_state.generated_srt = response.text
                st.success("បំប្លែង និងបកប្រែជោគជ័យ!")

    if st.session_state.get('generated_srt'):
        st.text_area("លទ្ធផល SRT (ភាសាខ្មែរ)", st.session_state.generated_srt, height=300)
        if st.button("បន្តទៅការបញ្ចូលសម្លេង (Dubbing) ➡️", type="primary"):
            st.session_state.current_step = 1
            st.rerun()

# --- ទំព័រទី ២: DUBBING (រក្សាទុក Logic ដើម ប៉ុន្តែសម្រួលការបកប្រែ) ---
else:
    st.title("🎬 Step 2: AI Dubbing Professional")
    srt_input = st.session_state.get('generated_srt', "")
    
    if not srt_input:
        st.warning("⚠️ សូមបំពេញ Step 1 ជាមុនសិន!")
    else:
        if 'data' not in st.session_state:
            # បំប្លែង SRT ទៅជា DataFrame សម្រាប់កែសម្រួល
            subs = list(srt.parse(srt_input))
            data = []
            for i, s in enumerate(subs):
                data.append({
                    "ID": i, "Select": False, 
                    "Khmer_Text": s.content, 
                    "Voice": "Male", "Start": s.start, "End": s.end
                })
            st.session_state.data = data
        
        if st.session_state.get('data'):
            df = pd.DataFrame(st.session_state.data)
            edited_df = st.data_editor(df, use_container_width=True, hide_index=True,
                column_config={"Select": st.column_config.CheckboxColumn("រើស"), "Khmer_Text": st.column_config.TextColumn("អត្ថបទខ្មែរ", width="large"), "Voice": st.column_config.SelectboxColumn("ភេទ", options=["Male", "Female"]), "ID":None, "Start":None, "End":None})
            
            if st.button("💾 រក្សាទុក និងរៀបចំផលិតសម្លេង"):
                st.session_state.data = edited_df.to_dict('records')
                st.success("រក្សាទុកជោគជ័យ!")

            speed = st.slider("ល្បឿនសម្លេង (%)", -20, 20, 0)
            if st.button("🚀 START DUBBING", type="primary"):
                stat, pb = st.empty(), st.progress(0)
                final_audio = asyncio.run(process_audio_dubbing(st.session_state.data, speed, stat, pb))
                final_audio.export("output.mp3", format="mp3")
                with open("output.mp3", "rb") as f:
                    st.audio(f.read())
                    st.download_button("📥 ទាញយក MP3", f.read(), "reach_dubbing.mp3")

if st.sidebar.button("🚪 Logout"):
    st_javascript("localStorage.removeItem('last_active');")
    st.session_state.logged_in = False
    st.rerun()
