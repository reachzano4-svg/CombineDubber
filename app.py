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
st.set_page_config(page_title="Reach AI Final Pro", layout="wide")

# --- ២. ប្រព័ន្ធ Login ---
USER_NAME = "admin"
USER_PASSWORD = "reachzano"

if "logged_in" not in st.session_state: st.session_state.logged_in = False
if "current_step" not in st.session_state: st.session_state.current_step = 0
if "generated_srt" not in st.session_state: st.session_state.generated_srt = ""

def login():
    stored_user = st_javascript("localStorage.getItem('reach_user');")
    stored_pw = st_javascript("localStorage.getItem('reach_pw');")
    last_active = st_javascript("localStorage.getItem('last_active');")
    current_time = int(time.time())
    if last_active and str(stored_user) == USER_NAME:
        if (current_time - int(last_active)) < 180: st.session_state.logged_in = True
    if not st.session_state.logged_in:
        st.markdown("<h2 style='text-align: center;'>🔐 Reach AI Full Options</h2>", unsafe_allow_html=True)
        _, col2, _ = st.columns([1, 1.5, 1])
        with col2:
            user = st.text_input("Username", value=stored_user if stored_user else "")
            pw = st.text_input("Password", type="password", value=stored_pw if stored_pw else "")
            if st.button("ចូលប្រើ", type="primary", use_container_width=True):
                if user == USER_NAME and pw == USER_PASSWORD:
                    st.session_state.logged_in = True
                    st_javascript(f"localStorage.setItem('last_active', '{current_time}');")
                    st_javascript(f"localStorage.setItem('reach_user', '{user}');")
                    st_javascript(f"localStorage.setItem('reach_pw', '{pw}');")
                    st.rerun()
                else: st.error("ខុសលេខសម្ងាត់!")
        st.stop()
login()

# --- ៣. Helper Functions ---
def format_time(seconds):
    td = datetime.timedelta(seconds=seconds)
    total_sec = int(td.total_seconds())
    milis = int((td.total_seconds() - total_sec) * 1000)
    return f"{total_sec // 3600:02}:{(total_sec % 3600) // 60:02}:{total_sec % 60:02},{milis:03}"

def simplify_khmer(text):
    if not text: return ""
    replaces = {"តើ(.*)មែនទេ": r"\1មែនអត់?", "របស់អ្នក": "ឯង", "បាទ": "បាទបង", "ចាស": "ចា៎"}
    for p, r in replaces.items(): text = re.sub(p, r, text)
    return text.strip()

async def fast_tts(row_data, index, speed):
    voice = "km-KH-SreymomNeural" if row_data['Voice'] == "Female" else "km-KH-PisethNeural"
    tmp = f"t_{index}.mp3"
    await edge_tts.Communicate(str(row_data['Khmer_Text']), voice, rate=f"{speed:+}%").save(tmp)
    return tmp

# --- ៤. Navigation ---
st.sidebar.title(f"👤 Admin: Reach")
choice = st.sidebar.radio("ជំហានការងារ", ["Step 1: Transcribe", "Step 2: Dubbing"], index=st.session_state.current_step)
st.session_state.current_step = 0 if choice == "Step 1: Transcribe" else 1

# --- ៥. STEP 1: TRANSCRIBE ---
if st.session_state.current_step == 0:
    st.header("🎙️ Step 1: Video to SRT")
    video_file = st.file_uploader("Upload Video", type=["mp4", "mp3", "mov"])
    if st.button("🚀 ចាប់ផ្ដើមបំប្លែង", type="primary"):
        if video_file:
            with open("temp.mp4", "wb") as f: f.write(video_file.getbuffer())
            with st.spinner("🚀 កំពុងស្ដាប់..."):
                model = whisper.load_model("tiny")
                res = model.transcribe("temp.mp4", fp16=False)
            srt_out = ""
            for i, s in enumerate(res['segments']):
                srt_out += f"{i+1}\n{format_time(s['start'])} --> {format_time(s['end'])}\n{s['text'].strip()}\n\n"
            st.session_state.generated_srt = srt_out
            if os.path.exists("temp.mp4"): os.remove("temp.mp4")
            st.rerun()
    if st.session_state.generated_srt:
        st.text_area("លទ្ធផល SRT", st.session_state.generated_srt, height=200)
        st.button("បន្តទៅ Step 2 ➡️", on_click=lambda: setattr(st.session_state, 'current_step', 1))

# --- ៦. STEP 2: DUBBING (Full Features) ---
else:
    st.header("🎬 Step 2: AI Dubbing & Tools")
    if not st.session_state.generated_srt:
        st.warning("សូមធ្វើ Step 1 សិន!"); st.button("⬅️ Back", on_click=lambda: setattr(st.session_state, 'current_step', 0))
    else:
        if 'data' not in st.session_state:
            if st.button("📥 បកប្រែភាសា", type="primary"):
                subs = list(srt.parse(st.session_state.generated_srt))
                raw_texts = [s.content for s in subs]
                with st.spinner("⏳ កំពុងបកប្រែ..."):
                    km_texts = GoogleTranslator(source='auto', target='km').translate_batch(raw_texts)
                st.session_state.data = [{"ID": i, "Select": False, "English": raw_texts[i], "Khmer_Text": simplify_khmer(km_texts[i]), "Voice": "Male", "Start": s.start, "End": s.end} for i, s in enumerate(subs)]
                st.rerun()

        if st.session_state.get('data'):
            df = pd.DataFrame(st.session_state.data)
            tab_edit, tab_setting = st.tabs(["📝 កែសម្រួល & បញ្ជាលឿន", "⚙️ កំណត់សម្លេង & ផលិត"])
            
            with tab_edit:
                edited_df = st.data_editor(df, use_container_width=True, hide_index=True, 
                                           column_config={"Select": st.column_config.CheckboxColumn("រើស"), "Khmer_Text": st.column_config.TextColumn("អត្ថបទខ្មែរ", width="large"), "Voice": st.column_config.SelectboxColumn("ភេទ", options=["Male", "Female"]), "ID":None, "Start":None, "End":None, "English":None})
                
                col1, col2, col3, col4 = st.columns(4)
                if col1.button("🌸 ស្រីទាំងអស់"):
                    for item in st.session_state.data: item['Voice'] = "Female"; st.rerun()
                if col2.button("💎 ប្រុសទាំងអស់"):
                    for item in st.session_state.data: item['Voice'] = "Male"; st.rerun()
                if col3.button("👩‍🦰 Tick -> ស្រី"):
                    for i, r in edited_df.iterrows():
                        if r['Select']: st.session_state.data[i]['Voice'] = "Female"; st.rerun()
                if col4.button("👨‍🦱 Tick -> ប្រុស"):
                    for i, r in edited_df.iterrows():
                        if r['Select']: st.session_state.data[i]['Voice'] = "Male"; st.rerun()
                
                st.divider()
                c1, c2, c3 = st.columns(3)
                if c1.button("💾 Save", use_container_width=True): 
                    st.session_state.data = edited_df.to_dict('records'); st.success("Saved!")
                
                # CapCut Fix Download
                km_srt = srt.compose([srt.Subtitle(i+1, r['Start'], r['End'], r['Khmer_Text'].replace('\n',' ')) for i, r in enumerate(st.session_state.data)])
                c2.download_button("📥 EN SRT", st.session_state.generated_srt.encode('utf-8-sig'), "en.srt", use_container_width=True)
                c3.download_button("📥 KH SRT", km_srt.encode('utf-8-sig'), "kh.srt", use_container_width=True)

            with tab_setting:
                speed = st.slider("ល្បឿន (%)", -50, 50, 0)
                bgm_file = st.file_uploader("ថែមភ្លេង BGM", type=["mp3"])
                bgm_vol = st.slider("កម្រិតសម្លេង BGM (%)", 0, 100, 20)
                
                if st.button("🚀 START DUBBING", type="primary", use_container_width=True):
                    st.session_state.data = edited_df.to_dict('records')
                    async def run_tts():
                        return await asyncio.gather(*[fast_tts(r, i, speed) for i, r in enumerate(st.session_state.data)])
                    
                    with st.spinner("🎙️ ផលិតសម្លេង..."):
                        audio_files = asyncio.run(run_tts())
                        final_audio = AudioSegment.silent(duration=0)
                        curr_ms = 0
                        for i, r in enumerate(st.session_state.data):
                            start_ms = int(r['Start'].total_seconds() * 1000)
                            if start_ms > curr_ms: final_audio += AudioSegment.silent(duration=start_ms - curr_ms)
                            seg = AudioSegment.from_file(audio_files[i])
                            final_audio += seg; curr_ms = start_ms + len(seg)
                            os.remove(audio_files[i])
                        
                        if bgm_file:
                            bgm = AudioSegment.from_file(bgm_file) - (60 - (bgm_vol * 0.6))
                            final_audio = final_audio.overlay(bgm * (int(len(final_audio)/len(bgm)) + 1))
                            
                        final_audio.export("final.mp3", format="mp3")
                        with open("final.mp3", "rb") as f: st.session_state.audio_bytes = f.read()
                    st.success("រួចរាល់!")
                
                if st.session_state.get('audio_bytes'):
                    st.audio(st.session_state.audio_bytes)
                    st.download_button("📥 Download MP3", st.session_state.audio_bytes, "reach_final.mp3", type="primary")

        st.button("⬅️ ត្រលប់ក្រោយ", on_click=lambda: setattr(st.session_state, 'current_step', 0))
