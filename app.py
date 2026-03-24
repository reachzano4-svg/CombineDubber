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

# --- ១. កំណត់ Page Config & Theme ---
st.set_page_config(page_title="Reach Maverick AI Dubbing", layout="wide", page_icon="🎙️")

# --- ២. ប្រព័ន្ធ Login & Session State (រក្សាទុកដូចកូដដើមបង) ---
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
        if (current_time - int(last_active)) < 300:
            st.session_state.logged_in = True

    if not st.session_state.logged_in:
        st.markdown("<h1 style='text-align: center; color: #FF4B4B;'>🎙️ Reach Maverick AI Dubbing</h1>", unsafe_allow_html=True)
        st.markdown("<h3 style='text-align: center;'>🔐 សូមបញ្ចូលលេខសម្ងាត់ដើម្បីចូលប្រើ</h3>", unsafe_allow_html=True)
        _, col2, _ = st.columns([1, 1.2, 1])
        with col2:
            user = st.text_input("Username", value=stored_user if stored_user else "")
            pw = st.text_input("Password", type="password", value=stored_pw if stored_pw else "")
            if st.button("ចូលប្រើប្រព័ន្ធ", type="primary", use_container_width=True):
                if user == USER_NAME and pw == USER_PASSWORD:
                    st.session_state.logged_in = True
                    st_javascript(f"localStorage.setItem('last_active', '{current_time}');")
                    st_javascript(f"localStorage.setItem('reach_user', '{user}');")
                    st_javascript(f"localStorage.setItem('reach_pw', '{pw}');")
                    st.rerun()
                else: st.error("ខុសលេខសម្ងាត់! សូមព្យាយាមម្ដងទៀត។")
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
    subs = [srt.Subtitle(index=i+1, start=row['Start'], end=row['End'], content=str(row[lang_key]).replace('\n', ' ').strip()) for i, row in enumerate(data)]
    return srt.compose(subs)

async def fetch_tts_file(row_data, index, speed):
    voice = "km-KH-SreymomNeural" if row_data['Voice'] == "Female" else "km-KH-PisethNeural"
    tmp = f"t_{index}.mp3"
    await edge_tts.Communicate(str(row_data['Khmer_Text']), voice, rate=f"{speed:+}%").save(tmp)
    return tmp

# --- ៤. Sidebar Navigation ---
st.sidebar.markdown(f"<h2 style='color: #FF4B4B;'>Reach Maverick</h2>", unsafe_allow_html=True)
st.sidebar.write(f"👤 Admin: **Reach**")
step_list = ["Step 1: Transcribe", "Step 2: Dubbing"]
choice = st.sidebar.radio("ជំហានការងារ", step_list, index=st.session_state.current_step)
st.session_state.current_step = 0 if choice == step_list[0] else 1

if st.sidebar.button("🚪 Logout"):
    st_javascript("localStorage.removeItem('last_active');")
    st.session_state.logged_in = False
    st.rerun()

# --- ៥. STEP 1: TRANSCRIBE ---
if st.session_state.current_step == 0:
    st.header("🎙️ Step 1: Video/Audio to SRT")
    video_file = st.file_uploader("Upload File (MP4, MP3, MOV)", type=["mp4", "mp3", "mov", "m4a"])
    if st.button("🚀 ចាប់ផ្ដើមបំប្លែង", type="primary"):
        if video_file:
            with open("temp.mp4", "wb") as f: f.write(video_file.getbuffer())
            with st.spinner("កំពុងស្ដាប់ និងបំប្លែងអត្ថបទ..."):
                model = whisper.load_model("tiny")
                res = model.transcribe("temp.mp4", fp16=False)
            srt_out = ""
            for i, s in enumerate(res['segments']):
                srt_out += f"{i+1}\n{format_time(s['start'])} --> {format_time(s['end'])}\n{s['text'].strip()}\n\n"
            st.session_state.generated_srt = srt_out
            if os.path.exists("temp.mp4"): os.remove("temp.mp4")
            st.rerun()

    if st.session_state.generated_srt:
        st.text_area("លទ្ធផល SRT", st.session_state.generated_srt, height=250)
        c_reset, c_next = st.columns([5, 1])
        if c_reset.button("🗑️ Reset"): 
            st.session_state.generated_srt = ""; st.rerun()
        if c_next.button("បន្តទៅមុខ ➡️", type="primary", use_container_width=True):
            st.session_state.current_step = 1; st.rerun()

# --- ៦. STEP 2: DUBBING ---
else:
    st.header("🎬 Step 2: AI Dubbing & Tool")
    if not st.session_state.generated_srt:
        st.warning("⚠️ សូមបំពេញ Step 1 ជាមុនសិន!"); st.button("⬅️ Back", on_click=lambda: setattr(st.session_state, 'current_step', 0))
    else:
        if 'data' not in st.session_state:
            if st.button("📥 បកប្រែភាសាខ្មែរ (Turbo)", type="primary"):
                subs = list(srt.parse(st.session_state.generated_srt))
                raw_texts = [s.content for s in subs]
                with st.spinner("⏳ កំពុងបកប្រែជាក្រុម..."):
                    km_texts = GoogleTranslator(source='auto', target='km').translate_batch(raw_texts)
                st.session_state.data = [{"ID": i, "Select": False, "English": raw_texts[i], "Khmer_Text": simplify_khmer(km_texts[i]), "Voice": "Male", "Start": s.start, "End": s.end} for i, s in enumerate(subs)]
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
                        "ID":None, "Start":None, "End":None, "English":st.column_config.TextColumn("អង់គ្លេស", disabled=True)
                    })
                
                st.write("🔧 បញ្ជាលឿន (Quick Controls):")
                c1, c2, c3, c4 = st.columns(4)
                if c1.button("🌸 ស្រីទាំងអស់"):
                    for item in st.session_state.data: item['Voice'] = "Female"; st.rerun()
                if c2.button("💎 ប្រុសទាំងអស់"):
                    for item in st.session_state.data: item['Voice'] = "Male"; st.rerun()
                if c3.button("👩‍🦰 Tick -> ស្រី"):
                    for i, r in edited_df.iterrows():
                        if r['Select']: st.session_state.data[i]['Voice'] = "Female"; st.rerun()
                if c4.button("👨‍🦱 Tick -> ប្រុស"):
                    for i, r in edited_df.iterrows():
                        if r['Select']: st.session_state.data[i]['Voice'] = "Male"; st.rerun()
                
                st.divider()
                cs1, cs2, cs3 = st.columns(3)
                if cs1.button("💾 រក្សាទុកការកែ", use_container_width=True):
                    st.session_state.data = edited_df.to_dict('records'); st.success("រក្សាទុកជោគជ័យ!")
                cs2.download_button("📥 EN SRT", create_srt_content(st.session_state.data, "English").encode('utf-8-sig'), "en.srt", use_container_width=True)
                cs3.download_button("📥 KH SRT", create_srt_content(st.session_state.data, "Khmer_Text").encode('utf-8-sig'), "kh.srt", use_container_width=True)

            with tab_setting:
                speed = st.slider("ល្បឿននិយាយ (%)", -50, 50, 0)
                bgm_file = st.file_uploader("ភ្លេង BGM (Optional)", type=["mp3"])
                bgm_vol = st.slider("កម្រិតសម្លេង BGM", 0, 100, 20)
            
            with tab_process:
                if st.button("🚀 START TURBO DUBBING", type="primary", use_container_width=True):
                    st.session_state.data = edited_df.to_dict('records')
                    async def run_dub():
                        return await asyncio.gather(*[fetch_tts_file(row, i, speed) for i, row in enumerate(st.session_state.data)])

                    with st.spinner("🎙️ កំពុងផលិតសម្លេងរលូនតាម Timeline..."):
                        audio_files = asyncio.run(run_dub())
                        combined = AudioSegment.silent(duration=0)
                        curr_ms = 0
                        for i, row in enumerate(st.session_state.data):
                            start_ms = int(row['Start'].total_seconds() * 1000)
                            end_ms = int(row['End'].total_seconds() * 1000)
                            
                            seg = AudioSegment.from_file(audio_files[i]).strip_silence()
                            dur = max(1, end_ms - start_ms)
                            if len(seg) > (dur + 300):
                                seg = speedup(seg, playback_speed=min(len(seg)/dur, 1.4), chunk_size=150, crossfade=25)
                            
                            if start_ms > curr_ms:
                                combined += AudioSegment.silent(duration=start_ms - curr_ms)
                                combined += seg
                            else:
                                combined = combined.append(seg, crossfade=100) # រលាយឃ្លាចូលគ្នា
                            
                            curr_ms = len(combined)
                            os.remove(audio_files[i])
                        
                        if bgm_file:
                            bgm = AudioSegment.from_file(bgm_file) - (60 - (bgm_vol * 0.6))
                            combined = combined.overlay(bgm * (int(len(combined)/len(bgm)) + 1))
                        
                        combined.export("final.mp3", format="mp3")
                        with open("final.mp3", "rb") as f: st.session_state.audio_bytes = f.read()
                    st.success("ផលិតរួចរាល់!")
                
                if st.session_state.get('audio_bytes'):
                    st.audio(st.session_state.audio_bytes)
                    st.download_button("📥 ទាញយក MP3", st.session_state.audio_bytes, "reach_maverick_dub.mp3", type="primary", use_container_width=True)

        st.divider()
        st.button("⬅️ Back to Step 1", on_click=lambda: setattr(st.session_state, 'current_step', 0))
