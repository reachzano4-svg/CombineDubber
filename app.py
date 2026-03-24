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

# --- ១. កំណត់ Page Config & Custom UI (ស្អាតជាងមុន) ---
st.set_page_config(page_title="Reach AI Pro", layout="wide", page_icon="🎙️")

st.markdown("""
    <style>
    .stApp { background-color: #0E1117; }
    h1, h2, h3 { color: #D4AF37 !important; font-family: 'Kantumruy Pro', sans-serif; }
    .stButton>button {
        background: linear-gradient(145deg, #D4AF37, #B8860B) !important;
        color: black !important;
        font-weight: bold !important;
        border-radius: 10px !important;
        border: none !important;
        transition: 0.3s;
    }
    .stButton>button:hover { transform: scale(1.02); box-shadow: 0px 4px 15px rgba(212, 175, 55, 0.4); }
    .stTextInput>div>div>input { border-color: #D4AF37 !important; }
    </style>
    """, unsafe_allow_html=True)

# --- ២. ប្រព័ន្ធ Login (ចងចាំ Password) ---
USER_NAME = "admin"
USER_PASSWORD = "reachzano"

def login():
    # ទាញយកទិន្នន័យដែលធ្លាប់ Save ទុក
    stored_user = st_javascript("localStorage.getItem('reach_user');")
    stored_pw = st_javascript("localStorage.getItem('reach_pw');")
    last_active = st_javascript("localStorage.getItem('last_active');")
    
    current_time = int(time.time())
    timeout_seconds = 600 # បង្កើនពេលដល់ ១០នាទី កុំឱ្យឆាប់កាត់ Login បងពេក

    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    # ឆែក Login អូតូ បើមានទិន្នន័យស្រាប់
    if not st.session_state.logged_in and stored_user == USER_NAME and stored_pw == USER_PASSWORD:
        if last_active and (current_time - int(last_active)) < timeout_seconds:
            st.session_state.logged_in = True

    if not st.session_state.logged_in:
        st.markdown("<h1 style='text-align: center;'>🎙️ REACH MAVERICK PRO</h1>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1.2, 1])
        with col2:
            # ដាក់ value ឱ្យវាចាំឈ្មោះ និងលេខសម្ងាត់តែម្ដង
            u = st.text_input("Username", value=stored_user if stored_user else "")
            p = st.text_input("Password", type="password", value=stored_pw if stored_pw else "")
            rem = st.checkbox("ចងចាំការចូលប្រើលើកក្រោយ (Always Remember)", value=True)
            
            if st.button("ចូលប្រើប្រាស់ AI", type="primary", use_container_width=True):
                if u == USER_NAME and p == USER_PASSWORD:
                    st_javascript(f"localStorage.setItem('last_active', '{current_time}');")
                    if rem:
                        st_javascript(f"localStorage.setItem('reach_user', '{u}');")
                        st_javascript(f"localStorage.setItem('reach_pw', '{p}');")
                    st.session_state.logged_in = True
                    st.rerun()
                else:
                    st.error("ខុសឈ្មោះ ឬលេខសម្ងាត់!")
        st.stop()
    else:
        st_javascript(f"localStorage.setItem('last_active', '{current_time}');")

login()

# --- ៣. Helper Functions (រក្សាកូដបង ១០០%) ---
def format_time(seconds):
    td = datetime.timedelta(seconds=seconds)
    total_sec = int(td.total_seconds())
    milis = int((td.total_seconds() - total_sec) * 1000)
    return f"{total_sec // 3600:02}:{(total_sec % 3600) // 60:02}:{total_sec % 60:02},{milis:03}"

def simplify_khmer(text):
    if not text: return ""
    reps = {"តើ(.*)មែនទេ": r"\1មែនអត់?", "របស់អ្នក": "ឯង", "បាទ": "បាទបង", "ចាស": "ចា៎"}
    for p, r in reps.items(): text = re.sub(p, r, text)
    return text.strip()

def create_srt_download(data, lang_key):
    subs = []
    for i, row in enumerate(data):
        subs.append(srt.Subtitle(index=i+1, start=row['Start'], end=row['End'], content=row[lang_key]))
    return srt.compose(subs)

async def process_audio(data, base_speed, status, progress):
    combined = AudioSegment.silent(duration=0)
    current_ms = 0
    for i, row in enumerate(data):
        progress.progress((i + 1) / len(data))
        status.write(f"🎙️ ផលិតឃ្លាទី {i+1}...")
        text, start_ms, end_ms = str(row['Khmer_Text']).strip(), int(row['Start'].total_seconds()*1000), int(row['End'].total_seconds()*1000)
        if start_ms > current_ms:
            combined += AudioSegment.silent(duration=start_ms - current_ms)
            current_ms = start_ms
        voice = "km-KH-SreymomNeural" if row['Voice'] == "Female" else "km-KH-PisethNeural"
        tmp = f"temp_{i}.mp3"
        await edge_tts.Communicate(text, voice, rate=f"{base_speed:+}%").save(tmp)
        if os.path.exists(tmp):
            seg = AudioSegment.from_file(tmp)
            if len(seg) > (end_ms - start_ms + 500):
                seg = speedup(seg, playback_speed=min(len(seg)/(end_ms - start_ms), 1.4), chunk_size=150, crossfade=25)
            combined += seg
            current_ms += len(seg)
            try: os.remove(tmp)
            except: pass
    return combined

# --- ៤. Navigation Logic ---
if 'current_step' not in st.session_state:
    st.session_state.current_step = 0

st.sidebar.markdown("<h2 style='text-align: center;'>MENU</h2>", unsafe_allow_html=True)
step_options = ["🏠 បំប្លែងវីដេអូ (Transcribe)", "🎧 បញ្ចូលសម្លេង (Dubbing)"]
selected_step = st.sidebar.radio("ជ្រើសរើសជំហាន", step_options, index=st.session_state.current_step)

if selected_step == step_options[0]: st.session_state.current_step = 0
else: st.session_state.current_step = 1

if st.sidebar.button("🚪 ចាកចេញ (Logout)", use_container_width=True):
    st_javascript("localStorage.removeItem('last_active');")
    st.session_state.logged_in = False
    st.rerun()

# --- ៥. STEP 0: TRANSCRIBE (សម្រួលឱ្យលឿនជាងមុន) ---
if st.session_state.current_step == 0:
    st.title("🎙️ Step 1: Video to SRT")
    if 'generated_srt' not in st.session_state: st.session_state.generated_srt = ""
    
    video_file = st.file_uploader("Upload វីដេអូ ឬសម្លេង", type=["mp4", "mp3", "mov", "m4a"])
    if st.button("🚀 ចាប់ផ្ដើមបំប្លែង (Fast Mode)", type="primary"):
        if video_file:
            with st.spinner("🚀 កំពុងស្ដាប់ និងបំប្លែងយ៉ាងរហ័ស..."):
                with open("temp.mp4", "wb") as f: f.write(video_file.getbuffer())
                
                # បង្កើនល្បឿនដោយប្រើ Tiny Model និង Initial Prompt
                model = whisper.load_model("base") # បើចង់លឿនបំផុតប្តូរទៅ "tiny"
                res = model.transcribe("temp.mp4", initial_prompt="Cambodian Khmer language transcription.")
                
                segments = res['segments']
                merged = []
                if segments:
                    curr = segments[0]
                    for next_seg in segments[1:]:
                        if (next_seg['start'] - curr['end']) < 0.5 and (next_seg['end'] - curr['start']) < 5.0:
                            curr['end'] = next_seg['end']; curr['text'] += " " + next_seg['text']
                        else: merged.append(curr); curr = next_seg
                    merged.append(curr)
                
                srt_out = ""
                for i, s in enumerate(merged):
                    srt_out += f"{i+1}\n{format_time(s['start'])} --> {format_time(s['end'])}\n{s['text'].strip()}\n\n"
                st.session_state.generated_srt = srt_out
                st.success("រួចរាល់!")

    if st.session_state.generated_srt:
        st.text_area("លទ្ធផល SRT", st.session_state.generated_srt, height=250)
        if st.button("បន្តទៅការបញ្ចូលសម្លេង ➡️", type="primary"):
            st.session_state.current_step = 1
            st.rerun()

# --- ៦. STEP 1: DUBBING ---
else:
    st.title("🎬 Step 2: AI Dubbing")
    srt_input = st.session_state.get('generated_srt', "")
    
    if not srt_input:
        st.warning("⚠️ សូមបំពេញ Step 1 ជាមុនសិន!")
    else:
        if 'data' not in st.session_state:
            if st.button("📥 បកប្រែអត្ថបទអូតូ", type="primary"):
                subs = list(srt.parse(srt_input))
                tr_en, tr_km = GoogleTranslator(source='auto', target='en'), GoogleTranslator(source='en', target='km')
                data = []
                p = st.empty()
                for i, s in enumerate(subs):
                    p.write(f"បកប្រែឃ្លាទី {i+1}...")
                    en = tr_en.translate(s.content)
                    km = simplify_khmer(tr_km.translate(en))
                    data.append({"ID": i, "Select": False, "English": en, "Khmer_Text": km, "Voice": "Male", "Start": s.start, "End": s.end})
                st.session_state.data = data; st.rerun()

        if st.session_state.get('data'):
            df = pd.DataFrame(st.session_state.data)
            tab_edit, tab_setting, tab_process = st.tabs(["📝 កែអត្ថបទ", "⚙️ កំណត់សម្លេង", "🎵 ផលិត MP3"])
            
            with tab_edit:
                edited_df = st.data_editor(df, use_container_width=True, hide_index=True,
                    column_config={"Select": st.column_config.CheckboxColumn("រើស", default=False), "English": st.column_config.TextColumn("EN", disabled=True), "Khmer_Text": st.column_config.TextColumn("KH", width="large"), "Voice": st.column_config.SelectboxColumn("ភេទ", options=["Male", "Female"]), "ID":None, "Start":None, "End":None})
                if st.button("💾 រក្សាទុក"):
                    st.session_state.data = edited_df.to_dict('records'); st.success("Saved!")

            with tab_setting:
                speed = st.slider("ល្បឿន (%)", -50, 50, 0)
                bgm = st.file_uploader("ថែមភ្លេង Background (BGM)", type=["mp3"])
                vol = st.slider("កម្រិតសម្លេង BGM", 0, 100, 20)
            
            with tab_process:
                if st.button("🚀 START DUBBING", type="primary", use_container_width=True):
                    stat, pb = st.empty(), st.progress(0)
                    res = asyncio.run(process_audio(st.session_state.data, speed, stat, pb))
                    if bgm:
                        back = AudioSegment.from_file(bgm) - (60 - (vol * 0.6))
                        res = res.overlay(back * (int(len(res)/len(back)) + 1))
                    res.export("final.mp3", format="mp3")
                    with open("final.mp3", "rb") as f: st.session_state.final_voice = f.read()
                    st.success("ជោគជ័យ!")
                
                if st.session_state.get('final_voice'):
                    st.audio(st.session_state.final_voice)
                    st.download_button("📥 ទាញយក MP3", st.session_state.final_voice, "reach_dub.mp3")
