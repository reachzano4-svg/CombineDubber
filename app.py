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
st.set_page_config(page_title="Reach AI Pro", layout="wide", page_icon="🎙️")

# --- ២. ប្រព័ន្ធ Login (ចងចាំ Password & Timeout 3mn) ---
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

    # Check login automatically if data exists
    if not st.session_state.logged_in and stored_user == USER_NAME and stored_pw == USER_PASSWORD:
        if last_active and (current_time - int(last_active)) < timeout_seconds:
            st.session_state.logged_in = True

    if not st.session_state.logged_in:
        st.markdown("<h2 style='text-align: center;'>🔐 ចូលប្រើប្រាស់ Reach AI</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col2:
            user = st.text_input("Username", value=stored_user if stored_user else "")
            pw = st.text_input("Password", type="password", value=stored_pw if stored_pw else "")
            remember = st.checkbox("ចងចាំលេខសម្ងាត់ (Remember Me)", value=True)
            if st.button("ចូលប្រើ", type="primary", use_container_width=True):
                if user == USER_NAME and pw == USER_PASSWORD:
                    st_javascript(f"localStorage.setItem('last_active', '{current_time}');")
                    if remember:
                        st_javascript(f"localStorage.setItem('reach_user', '{user}');")
                        st_javascript(f"localStorage.setItem('reach_pw', '{pw}');")
                    st.session_state.logged_in = True
                    st.rerun()
                else:
                    st.error("ខុសឈ្មោះ ឬលេខសម្ងាត់!")
        st.stop()
    else:
        st_javascript(f"localStorage.setItem('last_active', '{current_time}');")

login()

# --- ៣. Helper Functions ---
def format_time(seconds):
    td = datetime.timedelta(seconds=seconds)
    total_sec = int(td.total_seconds())
    milis = int((td.total_seconds() - total_sec) * 1000)
    return f"{total_sec // 3600:02}:{(total_sec % 3600) // 60:02}:{total_sec % 60:02},{milis:03}"

# មុខងារថ្មី៖ ហែកអត្ថបទតាមចំនួនពាក្យ (ដូច TurboScribe)
def split_segments_by_words(segments, max_words):
    new_segments = []
    for seg in segments:
        words = seg['text'].strip().split()
        if len(words) <= max_words:
            new_segments.append(seg)
            continue
        
        total_dur = seg['end'] - seg['start']
        for i in range(0, len(words), max_words):
            chunk = words[i:i + max_words]
            s_off = (i / len(words)) * total_dur
            e_off = (min(i + max_words, len(words)) / len(words)) * total_dur
            new_segments.append({
                'start': seg['start'] + s_off,
                'end': seg['start'] + e_off,
                'text': " ".join(chunk)
            })
    return new_segments

def simplify_khmer(text):
    if not text: return ""
    replaces = {"តើ(.*)មែនទេ": r"\1មែនអត់?", "របស់អ្នក": "ឯង", "បាទ": "បាទបង", "ចាស": "ចា៎"}
    for p, r in replaces.items(): text = re.sub(p, r, text)
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

step_options = ["🏠 បំប្លែងវីដេអូ (Transcribe)", "🎧 បញ្ចូលសម្លេង (Dubbing)"]
selected_step = st.sidebar.radio("ជំហានការងារ", step_options, index=st.session_state.current_step)

if selected_step == step_options[0]: st.session_state.current_step = 0
else: st.session_state.current_step = 1

if st.sidebar.button("🚪 Logout"):
    st_javascript("localStorage.removeItem('last_active');")
    st.session_state.logged_in = False
    st.rerun()

# --- ៥. STEP 0: TRANSCRIBE (Upgrade ល្បឿន និង Word Limit) ---
if st.session_state.current_step == 0:
    st.title("🎙️ Step 1: Video to SRT")
    if 'generated_srt' not in st.session_state: st.session_state.generated_srt = ""
    
    video_file = st.file_uploader("ជ្រើសរើសវីដេអូ ឬសម្លេង", type=["mp4", "mp3", "mov", "m4a"])
    
    # settings ដូចក្នុងរូបភាពបងផ្ញើមក
    st.markdown("### ⚙️ Settings")
    max_words_input = st.number_input("Max Words Per Segment", min_value=1, max_value=30, value=8)

    if st.button("🚀 TRANSCRIBE FILES", type="primary", use_container_width=True):
        if video_file:
            with st.spinner("⚡ កំពុងបំប្លែងយ៉ាងរហ័ស..."):
                with open("temp.mp4", "wb") as f: f.write(video_file.getbuffer())
                
                # ប្តូរប្រើ Tiny Model ដើម្បីល្បឿន
                model = whisper.load_model("tiny")
                res = model.transcribe("temp.mp4", fp16=False)
                
                # ហែកឃ្លាតាម Word Limit
                raw_segments = res['segments']
                final_segments = split_segments_by_words(raw_segments, max_words_input)
                
                srt_out = ""
                for i, s in enumerate(final_segments):
                    srt_out += f"{i+1}\n{format_time(s['start'])} --> {format_time(s['end'])}\n{s['text'].strip()}\n\n"
                
                st.session_state.generated_srt = srt_out
                st.success("បំប្លែងរួចរាល់!")
                if os.path.exists("temp.mp4"): os.remove("temp.mp4")

    if st.session_state.generated_srt:
        st.text_area("លទ្ធផល SRT (បែងចែកតាមចំនួនពាក្យ)", st.session_state.generated_srt, height=250)
        if st.button("បន្តទៅការបញ្ចូលសម្លេង ➡️", type="primary", use_container_width=True):
            st.session_state.current_step = 1
            st.rerun()

# --- ៦. STEP 1: DUBBING (រក្សាទុក Logic ដើមបងទាំងអស់) ---
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
                    column_config={"Select": st.column_config.CheckboxColumn("រើស", default=False), "English": st.column_config.TextColumn("EN", disabled=True), "Khmer_Text": st.column_config.TextColumn("KH", width="large"), "Voice": st.column_config.SelectboxColumn("ភេទ", options=["Male", "Female"]), "ID":None, "Start":None, "End":None})
                
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
                    st.download_button("📥 ទាញយក MP3", st.session_state.final_voice, "reach_dub.mp3")

    if st.button("⬅️ ត្រលប់ក្រោយ"):
        st.session_state.current_step = 0
        st.rerun()
