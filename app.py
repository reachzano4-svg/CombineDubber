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
                    st.session_state.current_step = "Transcribe" # ចាប់ផ្តើមជំហានដំបូង
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

# --- ៤. Navigation System ---
if 'current_step' not in st.session_state:
    st.session_state.current_step = "Transcribe"

st.sidebar.title(f"👤 {USER_NAME}")
nav = st.sidebar.radio("ជំហានការងារ", ["បំប្លែងវីដេអូ (Transcribe)", "បញ្ចូលសម្លេង (Dubbing)"], 
                       index=0 if st.session_state.current_step == "Transcribe" else 1, key="sidebar_nav")

# ធ្វើឱ្យ Navigation ក្នុង Sidebar Sync ជាមួយប៊ូតុង Next/Back
if nav == "បំប្លែងវីដេអូ (Transcribe)": st.session_state.current_step = "Transcribe"
else: st.session_state.current_step = "Dubbing"

if st.sidebar.button("🚪 Logout"):
    st_javascript("localStorage.removeItem('last_active');")
    st.session_state.logged_in = False
    st.rerun()

# --- ៥. ទំព័រទី ១: TRANSCRIBE ---
if st.session_state.current_step == "Transcribe":
    st.title("🎙️ Step 1: Video to SRT")
    if 'generated_srt' not in st.session_state: st.session_state.generated_srt = ""
    
    video_file = st.file_uploader("ជ្រើសរើសវីដេអូ", type=["mp4", "mp3", "mov", "m4a"])
    if st.button("🚀 ចាប់ផ្ដើមបំប្លែង", type="primary"):
        if video_file:
            with st.spinner("កំពុងស្តាប់..."):
                with open("temp.mp4", "wb") as f: f.write(video_file.getbuffer())
                model = whisper.load_model("base")
                res = model.transcribe("temp.mp4")
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
                st.session_state.generated_srt = srt_out; st.success("បំប្លែងរួចរាល់!")

    if st.session_state.generated_srt:
        st.text_area("លទ្ធផល SRT", st.session_state.generated_srt, height=250)
        st.divider()
        col_n1, col_n2 = st.columns([5, 1])
        with col_n1:
            if st.button("🗑️ Reset Data"): st.session_state.generated_srt = ""; st.rerun()
        with col_n2:
            if st.button("បន្តទៅមុខ ➡️", type="primary"):
                st.session_state.current_step = "Dubbing"
                st.rerun()

# --- ៦. ទំព័រទី ២: DUBBING ---
else:
    st.title("🎬 Step 2: AI Dubbing")
    srt_input = st.session_state.get('generated_srt', "")
    
    if srt_input and 'data' not in st.session_state:
        if st.button("📥 ចាប់ផ្ដើមបកប្រែអត្ថបទពី Step 1", type="primary"):
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
            
            st.divider()
            # ប៊ូតុងបញ្ជាលឿន
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
            
            c_s1, c_s2, c_s3 = st.columns(3)
            with c_s1:
                if st.button("💾 រក្សាទុកការកែ", use_container_width=True):
                    st.session_state.data = edited_df.to_dict('records'); st.success("Saved!")
            with c_s2:
                if st.button("📥 Download EN SRT", use_container_width=True):
                    st.download_button("ចុចទីនេះ", create_srt_download(st.session_state.data, "English").encode('utf-8-sig'), "en.srt")
            with c_s3:
                if st.button("📥 Download KH SRT", use_container_width=True):
                    st.download_button("ចុចទីនេះ", create_srt_download(st.session_state.data, "Khmer_Text").encode('utf-8-sig'), "kh.srt")

        with tab_setting:
            speed = st.slider("ល្បឿន (%)", -50, 50, 0)
            bgm = st.file_uploader("BGM", type=["mp3"])
            vol = st.slider("កម្រិតសម្លេង BGM", 0, 100, 20)
        
        with tab_process:
            if st.button("🚀 START DUBBING", type="primary"):
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

    st.divider()
    if st.button("⬅️ ត្រលប់ក្រោយ"):
        st.session_state.current_step = "Transcribe"
        st.rerun()
