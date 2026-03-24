import os
import time
import datetime
import asyncio
import edge_tts
import srt
import re  # <--- បន្ថែម re សម្រាប់ simplify_khmer
import pandas as pd
import google.generativeai as genai
import streamlit as st
from pydub import AudioSegment
from pydub.effects import speedup
from streamlit_javascript import st_javascript

# --- ដោះស្រាយបញ្ហា Audioop សម្រាប់ Python 3.13+ ---
try:
    import audioop
except ImportError:
    try:
        import audioop_lts as audioop
        import sys
        sys.modules['audioop'] = audioop
    except ImportError:
        pass

# --- ១. កំណត់ Page Config & API ---
st.set_page_config(page_title="Reach AI Maverick Pro", layout="wide", page_icon="🎬")

# កំណត់ API Key របស់បង Reach
API_KEY = "AIzaSyA4cqoTPWFsavOCEra_0aTJ-r7HciPnBto"
genai.configure(api_key=API_KEY)

# --- ២. ប្រព័ន្ធ Login ---
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
        if elapsed <= timeout_seconds:
            st.session_state.logged_in = True
    
    if not st.session_state.logged_in:
        st.markdown("<h2 style='text-align: center;'>🔐 Reach AI Maverick Pro Login</h2>", unsafe_allow_html=True)
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

# --- ៣. Helper Functions ---
def simplify_khmer(text):
    if not text: return ""
    # ប្រើ re.sub ដើម្បីប្តូរពាក្យឱ្យសមរម្យ
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
                seg = speedup(seg, playback_speed=min(len(seg)/max(duration_limit,1), 1.4))
            combined += seg
            current_ms += len(seg)
            os.remove(tmp)
    return combined

# --- ៤. Main UI Logic ---
if 'current_step' not in st.session_state: st.session_state.current_step = 0

step_options = ["🎙️ Transcribe & Translate (Smart)", "🎬 AI Dubbing Professional"]
selected_step = st.sidebar.radio("ជំហានការងារ", step_options, index=st.session_state.current_step)
st.session_state.current_step = 0 if selected_step == step_options[0] else 1

# --- ទំព័រទី ១: TRANSCRIBE & TRANSLATE ---
if st.session_state.current_step == 0:
    st.title("🎙️ Step 1: Gemini AI Cinema Intelligence")
    video_file = st.file_uploader("ជ្រើសរើសវីដេអូ ឬសម្លេងរឿងភាគចិន", type=["mp4", "mp3", "mov", "m4a"])
    
    if st.button("🚀 ចាប់ផ្ដើមបំប្លែងជាមួយ Gemini", type="primary", use_container_width=True):
        if video_file:
            with st.spinner("Gemini កំពុងស្ដាប់ និងបកប្រែជាភាសារឿងភាគចិន..."):
                with open("temp_input", "wb") as f: f.write(video_file.getbuffer())
                
                gemini_file = genai.upload_file(path="temp_input")
                while gemini_file.state.name == "PROCESSING":
                    time.sleep(2)
                    gemini_file = genai.get_file(gemini_file.name)
                
                model = genai.GenerativeModel(model_name="gemini-1.5-flash")
                
                # Prompt ថ្មីសម្រាប់បង Reach - បែបរឿងភាគចិន
                prompt = (
                    "Task: Transcribe and translate this audio into professional SRT format.\n"
                    "Style: Modern Chinese Youth Drama (Dubbing style).\n"
                    "Language: Natural, Conversational Khmer.\n"
                    "Instructions:\n"
                    "1. Use appropriate pronouns based on context: 'បង', 'អូន', 'ឯង', 'យើង', 'ខ្ញុំ'.\n"
                    "2. Make the dialogue sound emotional and smooth, like a real movie dubbing.\n"
                    "3. Format: Strictly output ONLY the raw SRT content with correct timecodes."
                )
                
                response = model.generate_content([prompt, gemini_file])
                st.session_state.generated_srt = response.text
                st.success("បំប្លែង និងបកប្រែជោគជ័យ!")
                if os.path.exists("temp_input"): os.remove("temp_input")

    if st.session_state.get('generated_srt'):
        st.text_area("លទ្ធផល SRT សម្រាប់រឿងភាគ", st.session_state.generated_srt, height=350)
        if st.button("បន្តទៅការបញ្ចូលសម្លេង (Dubbing) ➡️", type="primary", use_container_width=True):
            st.session_state.current_step = 1; st.rerun()

# --- ទំព័រទី ២: DUBBING ---
else:
    st.title("🎬 Step 2: AI Dubbing Professional")
    srt_input = st.session_state.get('generated_srt', "")
    
    if not srt_input:
        st.warning("⚠️ សូមបំពេញ Step 1 ជាមុនសិន!")
    else:
        if 'data' not in st.session_state:
            subs = list(srt.parse(srt_input))
            data = []
            for i, s in enumerate(subs):
                data.append({
                    "ID": i, "Select": False, 
                    "Khmer_Text": simplify_khmer(s.content), 
                    "Voice": "Male", "Start": s.start, "End": s.end
                })
            st.session_state.data = data
        
        if st.session_state.get('data'):
            df = pd.DataFrame(st.session_state.data)
            edited_df = st.data_editor(df, use_container_width=True, hide_index=True,
                column_config={"Select": st.column_config.CheckboxColumn("រើស"), "Khmer_Text": st.column_config.TextColumn("អត្ថបទខ្មែរ", width="large"), "Voice": st.column_config.SelectboxColumn("ភេទ", options=["Male", "Female"]), "ID":None, "Start":None, "End":None})
            
            if st.button("💾 រក្សាទុកការកែសម្រួល"):
                st.session_state.data = edited_df.to_dict('records')
                st.success("Saved!")

            speed = st.slider("ល្បឿនសម្លេង (%)", -20, 20, 0)
            if st.button("🚀 START DUBBING", type="primary", use_container_width=True):
                stat, pb = st.empty(), st.progress(0)
                final_audio = asyncio.run(process_audio_dubbing(st.session_state.data, speed, stat, pb))
                final_audio.export("output.mp3", format="mp3")
                with open("output.mp3", "rb") as f:
                    voice_data = f.read()
                    st.audio(voice_data)
                    st.download_button("📥 ទាញយក MP3", voice_data, "reach_maverick_dub.mp3")

if st.sidebar.button("🚪 Logout"):
    st_javascript("localStorage.removeItem('last_active');")
    st.session_state.logged_in = False
    st.rerun()
