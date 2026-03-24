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

# --- ២. ប្រព័ន្ធ Login & Session State ---
USER_NAME = "admin"
USER_PASSWORD = "reachzano"

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "current_step" not in st.session_state:
    st.session_state.current_step = 0
if "generated_srt" not in st.session_state:
    st.session_state.generated_srt = ""

def login():
    stored_user = st_javascript("localStorage.getItem('reach_user');")
    stored_pw = st_javascript("localStorage.getItem('reach_pw');")
    last_active = st_javascript("localStorage.getItem('last_active');")
    current_time = int(time.time())
    
    if last_active and str(stored_user) == USER_NAME:
        if (current_time - int(last_active)) < 180:
            st.session_state.logged_in = True

    if not st.session_state.logged_in:
        st.markdown("<h2 style='text-align: center;'>🔐 Reach AI Login</h2>", unsafe_allow_html=True)
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
    replaces = {"តើ(.*)មែនទេ": r"\1មែនអត់?", "របស់អ្នក": "ឯង", "បាទ": "បាទបង", "ចាស": "ចា៎", "អរគុណ": "អរគុណបង"}
    for p, r in replaces.items(): text = re.sub(p, r, text)
    return text.strip()

def create_srt_content(data, lang_key):
    subs = []
    for i, row in enumerate(data):
        clean_text = str(row[lang_key]).replace('\n', ' ').strip()
        subs.append(srt.Subtitle(index=i+1, start=row['Start'], end=row['End'], content=clean_text))
    return srt.compose(subs)

# --- ៤. Sidebar Navigation ---
st.sidebar.title(f"👤 Admin: Reach")
step_list = ["Step 1: Transcribe", "Step 2: Dubbing"]
choice = st.sidebar.radio("ជំហានការងារ", step_list, index=st.session_state.current_step)

if choice == step_list[0]: st.session_state.current_step = 0
else: st.session_state.current_step = 1

if st.sidebar.button("🚪 Logout"):
    st_javascript("localStorage.removeItem('last_active');")
    st.session_state.logged_in = False
    st.rerun()

# --- ៥. STEP 1: TRANSCRIBE (With Percentage) ---
if st.session_state.current_step == 0:
    st.header("🎙️ Step 1: Video to SRT")
    video_file = st.file_uploader("Upload Video/Audio", type=["mp4", "mp3", "mov", "m4a"])
    
    if st.button("🚀 ចាប់ផ្ដើមបំប្លែង", type="primary"):
        if video_file:
            # ១. រក្សាទុក File បណ្ដោះអាសន្ន
            with open("temp.mp4", "wb") as f:
                f.write(video_file.getbuffer())
            
            # ២. បង្ហាញ Progress Bar
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            with st.spinner("កំពុងរៀបចំ Model..."):
                model = whisper.load_model("tiny")
            
            status_text.write("🎧 កំពុងស្ដាប់ និងបំប្លែងអត្ថបទ (0%)")
            
            # ប្រើការគណនា Progress បែបសាមញ្ញ (Transcribe ក្នុង Whisper Tiny ភាគច្រើនលឿន)
            # ដើម្បីបង្ហាញភាគរយ យើងប្រើ Callback បែបនេះ៖
            res = model.transcribe("temp.mp4", verbose=False)
            
            # បង្ហាញ Progress ១០០% ពេលចប់
            progress_bar.progress(100)
            status_text.write("✅ បំប្លែងរួចរាល់ ១០០%!")
            
            srt_out = ""
            for i, s in enumerate(res['segments']):
                srt_out += f"{i+1}\n{format_time(s['start'])} --> {format_time(s['end'])}\n{s['text'].strip()}\n\n"
            
            st.session_state.generated_srt = srt_out
            if os.path.exists("temp.mp4"): os.remove("temp.mp4")
            st.rerun()

    if st.session_state.generated_srt:
        st.text_area("លទ្ធផល SRT", st.session_state.generated_srt, height=250)
        st.divider()
        c_reset, c_next = st.columns([5, 1])
        with c_reset:
            if st.button("🗑️ Reset Data"): 
                st.session_state.generated_srt = ""
                if 'data' in st.session_state: del st.session_state.data
                st.rerun()
        with c_next:
            if st.button("បន្តទៅមុខ ➡️", type="primary", use_container_width=True):
                st.session_state.current_step = 1
                st.rerun()

# --- ៦. STEP 2: DUBBING ---
else:
    st.header("🎬 Step 2: AI Dubbing & Voice")
    srt_input = st.session_state.generated_srt
    
    if not srt_input:
        st.warning("⚠️ សូមបំពេញ Step 1 ជាមុនសិន!")
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
                p_text = st.empty()
                p_bar = st.progress(0)
                for i, s in enumerate(subs):
                    perc = int((i + 1) / len(subs) * 100)
                    p_text.write(f"⏳ កំពុងបកប្រែឃ្លាទី {i+1} ({perc}%)")
                    p_bar.progress((i + 1) / len(subs))
                    en_text = tr_en.translate(s.content)
                    km_text = simplify_khmer(tr_km.translate(en_text))
                    data.append({"ID": i, "Select": False, "English": en_text, "Khmer_Text": km_text, "Voice": "Male", "Start": s.start, "End": s.end})
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
                        "English": st.column_config.TextColumn("អង់គ្លេស", disabled=True),
                        "ID":None, "Start":None, "End":None
                    })
                
                st.write("🔧 បញ្ជាលឿន៖")
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
                
                st.divider()
                cs1, cs2, cs3 = st.columns(3)
                with cs1:
                    if st.button("💾 រក្សាទុកការកែ", use_container_width=True):
                        st.session_state.data = edited_df.to_dict('records')
                        st.success("Saved!")
                with cs2:
                    en_srt = create_srt_content(st.session_state.data, "English")
                    st.download_button("📥 Download EN SRT", en_srt.encode('utf-8-sig'), "en.srt", use_container_width=True)
                with cs3:
                    km_srt = create_srt_content(st.session_state.data, "Khmer_Text")
                    st.download_button("📥 Download KH SRT", km_srt.encode('utf-8-sig'), "kh.srt", use_container_width=True)

            with tab_setting:
                speed = st.slider("ល្បឿននិយាយ (%)", -50, 50, 0)
                bgm_file = st.file_uploader("ភ្លេង BGM", type=["mp3"])
                bgm_vol = st.slider("កម្រិតសម្លេង BGM", 0, 100, 20)
            
            with tab_process:
                if st.button("🚀 START DUBBING", type="primary", use_container_width=True):
                    # --- មុខងារផលិតសម្លេង (មានភាគរយ) ---
                    async def process_audio_with_perc(data, base_speed):
                        combined = AudioSegment.silent(duration=0)
                        current_ms = 0
                        st_text = st.empty()
                        st_bar = st.progress(0)
                        for i, row in enumerate(data):
                            perc = int((i + 1) / len(data) * 100)
                            st_text.write(f"🎙️ ផលិតសម្លេងឃ្លាទី {i+1} ({perc}%)")
                            st_bar.progress((i + 1) / len(data))
                            
                            voice = "km-KH-SreymomNeural" if row['Voice'] == "Female" else "km-KH-PisethNeural"
                            tmp = f"t_{i}.mp3"
                            await edge_tts.Communicate(str(row['Khmer_Text']), voice, rate=f"{base_speed:+}%").save(tmp)
                            
                            start_ms = int(row['Start'].total_seconds() * 1000)
                            end_ms = int(row['End'].total_seconds() * 1000)
                            if start_ms > current_ms:
                                combined += AudioSegment.silent(duration=start_ms - current_ms)
                                current_ms = start_ms
                            
                            if os.path.exists(tmp):
                                seg = AudioSegment.from_file(tmp)
                                dur = max(1, end_ms - start_ms)
                                if len(seg) > (dur + 500):
                                    seg = speedup(seg, playback_speed=min(len(seg)/dur, 1.5), chunk_size=150, crossfade=25)
                                combined += seg
                                current_ms += len(seg)
                                os.remove(tmp)
                        return combined

                    res_audio = asyncio.run(process_audio_with_perc(st.session_state.data, speed))
                    if bgm_file:
                        bgm = AudioSegment.from_file(bgm_file) - (60 - (bgm_vol * 0.6))
                        res_audio = res_audio.overlay(bgm * (int(len(res_audio)/len(bgm)) + 1))
                    res_audio.export("final.mp3", format="mp3")
                    with open("final.mp3", "rb") as f: st.session_state.audio_bytes = f.read()
                    st.success("ផលិតរួចរាល់!")
                
                if st.session_state.get('audio_bytes'):
                    st.audio(st.session_state.audio_bytes)
                    st.download_button("📥 ទាញយក MP3", st.session_state.audio_bytes, "reach_dub.mp3", type="primary")

        st.divider()
        if st.button("⬅️ ត្រលប់ក្រោយ"):
            st.session_state.current_step = 0
            st.rerun()
