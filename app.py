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
import google.generativeai as genai
from pydub import AudioSegment
from pydub.effects import speedup
from deep_translator import GoogleTranslator
from streamlit_javascript import st_javascript

# --- ១. កំណត់ Page Config ---
st.set_page_config(page_title="Reach AI Pro", layout="wide", page_icon="🎙️")

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
        if (current_time - int(last_active)) <= timeout_seconds:
            st.session_state.logged_in = True
    
    if not st.session_state.logged_in:
        st.markdown("<h2 style='text-align: center;'>🔐 ចូលប្រើប្រាស់ Reach AI</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col2:
            user = st.text_input("Username", value=stored_user if stored_user else "")
            pw = st.text_input("Password", type="password", value=stored_pw if stored_pw else "")
            if st.button("ចូលប្រើ", type="primary", use_container_width=True):
                if user == USER_NAME and pw == USER_PASSWORD:
                    st.session_state.logged_in = True
                    st.session_state.current_step = 0
                    st_javascript(f"localStorage.setItem('last_active', '{current_time}');")
                    st_javascript(f"localStorage.setItem('reach_user', '{user}');")
                    st_javascript(f"localStorage.setItem('reach_pw', '{pw}');")
                    st.rerun()
                else: st.error("ខុសឈ្មោះ ឬលេខសម្ងាត់!")
        st.stop()
    else:
        st_javascript(f"localStorage.setItem('last_active', '{current_time}');")

login()

# --- ៣. Gemini API Configuration (Front-end Management) ---
st.sidebar.markdown("### 🔑 API Configuration")
api_key_input = st.sidebar.text_input("Gemini API Key", type="password", help="ប្តូរលេខថ្មីនៅទីនេះពេលអស់ Free Tier")
if api_key_input:
    genai.configure(api_key=api_key_input)
    st.session_state.api_ready = True
else:
    st.sidebar.warning("⚠️ សូមបំពេញ Gemini API Key")
    st.session_state.api_ready = False

# --- ៤. Helper Functions ---
def format_time(seconds):
    td = datetime.timedelta(seconds=seconds)
    total_sec = int(td.total_seconds())
    milis = int((td.total_seconds() - total_sec) * 1000)
    return f"{total_sec // 3600:02}:{(total_sec % 3600) // 60:02}:{total_sec % 60:02},{milis:03}"

def gemini_refine_srt(raw_srt):
    if not st.session_state.api_ready:
        return raw_srt
    
    prompt = f"""
    តួនាទី៖ អ្នកជំនាញ Dubbing រឿងភាគ។
    ភារកិច្ច៖ សម្រួលអត្ថបទ SRT ខាងក្រោមឱ្យត្រូវសាច់រឿង ខ្លី ខ្លឹម និងងាយស្រួល Dubbing (ប្រហែល ៧-១០ ពាក្យក្នុងមួយឃ្លា)។
    លក្ខខណ្ឌ៖
    1. រក្សា Timecode (00:00:00,000) ដាច់ខាត។
    2. លុបពាក្យដែលនិយាយស្ទួន ឬពាក្យ AI ស្ដាប់ច្រឡំ។
    3. បើឃ្លាវែងពេក ត្រូវហែកជា ២ ឃ្លាដោយបែងចែកពេលវេលាឱ្យសមស្រប។
    
    អត្ថបទ SRT៖
    {raw_srt}
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        st.error(f"❌ Gemini API Error: ប្រហែលជាអស់ Token ឬ Key ខុស។ សូមដូរលេខថ្មី! (Error: {str(e)})")
        return raw_srt

def simplify_khmer(text):
    if not text: return ""
    replaces = {"តើ(.*)មែនទេ": r"\1មែនអត់?", "របស់អ្នក": "ឯង", "បាទ": "បាទបង", "ចាស": "ចា៎"}
    for p, r in replaces.items(): text = re.sub(p, r, text)
    return text.strip()

def create_srt_download(data, lang_key):
    subs = [srt.Subtitle(index=i+1, start=row['Start'], end=row['End'], content=row[lang_key]) for i, row in enumerate(data)]
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
            combined += seg; current_ms += len(seg)
            try: os.remove(tmp)
            except: pass
    return combined

# --- ៥. Navigation Logic ---
if 'current_step' not in st.session_state: st.session_state.current_step = 0
step_options = ["បំប្លែងវីដេអូ (Transcribe)", "បញ្ចូលសម្លេង (Dubbing)"]
selected_step = st.sidebar.radio("ជំហានការងារ", step_options, index=st.session_state.current_step)
st.session_state.current_step = 0 if selected_step == step_options[0] else 1

if st.sidebar.button("🚪 Logout"):
    st_javascript("localStorage.clear();")
    st.session_state.logged_in = False
    st.rerun()

# --- ៦. Step 0: TRANSCRIBE + Smart Gemini ---
if st.session_state.current_step == 0:
    st.title("🎙️ Step 1: Video to Smart SRT")
    if 'generated_srt' not in st.session_state: st.session_state.generated_srt = ""
    
    video_file = st.file_uploader("ជ្រើសរើសវីដេអូ", type=["mp4", "mp3", "mov", "m4a"])
    
    if st.button("🚀 ចាប់ផ្ដើមបំប្លែង (Smart Mode)", type="primary", use_container_width=True):
        if video_file:
            with st.spinner("កំពុងបំប្លែង និងសម្រួលអត្ថបទដោយ Gemini..."):
                with open("temp.mp4", "wb") as f: f.write(video_file.getbuffer())
                
                # Whisper Transcribe
                model = whisper.load_model("tiny")
                res = model.transcribe("temp.mp4")
                
                # បង្កើត Raw SRT
                raw_srt = ""
                for i, s in enumerate(res['segments']):
                    raw_srt += f"{i+1}\n{format_time(s['start'])} --> {format_time(s['end'])}\n{s['text'].strip()}\n\n"
                
                # ផ្ញើទៅ Gemini (បងអាចដូរ Key ក្នុង Sidebar បើវាអស់ Token)
                refined_srt = gemini_refine_srt(raw_srt)
                st.session_state.generated_srt = refined_srt
                st.success("រួចរាល់!")

    if st.session_state.generated_srt:
        st.text_area("លទ្ធផល SRT ពី Gemini", st.session_state.generated_srt, height=250)
        if st.button("បន្តទៅមុខ ➡️", type="primary", use_container_width=True):
            st.session_state.current_step = 1; st.rerun()

# --- ៧. Step 1: DUBBING (Logic ដើមបងទាំងអស់) ---
else:
    st.title("🎬 Step 2: AI Dubbing")
    srt_input = st.session_state.get('generated_srt', "")
    
    if not srt_input:
        st.warning("⚠️ សូមបំពេញ Step 1 ជាមុនសិន!")
    else:
        if 'data' not in st.session_state:
            if st.button("📥 ចាប់ផ្ដើមបកប្រែអត្ថបទ", type="primary"):
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
                    column_config={"Select": st.column_config.CheckboxColumn("រើស"), "Khmer_Text": st.column_config.TextColumn("KH", width="large"), "Voice": st.column_config.SelectboxColumn("ភេទ", options=["Male", "Female"]), "ID":None, "Start":None, "End":None})
                if st.button("💾 រក្សាទុកការកែ"):
                    st.session_state.data = edited_df.to_dict('records'); st.success("Saved!")

            with tab_setting:
                speed = st.slider("ល្បឿន (%)", -50, 50, 0)
                bgm = st.file_uploader("BGM", type=["mp3"])
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
                    st.success("រួចរាល់!")
                if st.session_state.get('final_voice'):
                    st.audio(st.session_state.final_voice)
                    st.download_button("📥 ទាញយក MP3", st.session_state.final_voice, "dub_final.mp3")

    if st.button("⬅️ ត្រលប់ក្រោយ"):
        st.session_state.current_step = 0; st.rerun()
