import streamlit as st
import whisper
import datetime
import asyncio, edge_tts, srt, os, pandas as pd
from pydub import AudioSegment
from deep_translator import GoogleTranslator

# --- ១. កំណត់ Page Config ---
st.set_page_config(page_title="Reach AI Pro", layout="wide")

# --- ២. ប្រព័ន្ធ Login ---
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "current_step" not in st.session_state:
    st.session_state.current_step = 0

def login():
    if not st.session_state.logged_in:
        st.markdown("<h2 style='text-align: center;'>🔐 Login Reach AI</h2>", unsafe_allow_html=True)
        _, col2, _ = st.columns([1, 1.5, 1])
        with col2:
            user = st.text_input("Username")
            pw = st.text_input("Password", type="password")
            if st.button("ចូលប្រើ", type="primary", use_container_width=True):
                if user == "admin" and pw == "reachzano":
                    st.session_state.logged_in = True
                    st.rerun()
                else:
                    st.error("ខុសលេខសម្ងាត់!")
        st.stop()

login()

# --- ៣. Helper Functions ---
def format_time(seconds):
    td = datetime.timedelta(seconds=seconds)
    total_sec = int(td.total_seconds())
    milis = int((td.total_seconds() - total_sec) * 1000)
    return f"{total_sec // 3600:02}:{(total_sec % 3600) // 60:02}:{total_sec % 60:02},{milis:03}"

async def generate_voice(data, speed, status, progress):
    combined = AudioSegment.silent(duration=0)
    for i, row in enumerate(data):
        progress.progress((i + 1) / len(data))
        status.write(f"🎙️ ផលិតឃ្លាទី {i+1}...")
        voice = "km-KH-SreymomNeural" if row['Voice'] == "Female" else "km-KH-PisethNeural"
        tmp_mp3 = f"temp_{i}.mp3"
        await edge_tts.Communicate(row['Khmer_Text'], voice, rate=f"{speed:+}%").save(tmp_mp3)
        if os.path.exists(tmp_mp3):
            seg = AudioSegment.from_file(tmp_mp3)
            combined += seg
            os.remove(tmp_mp3)
    return combined

# --- ៤. Navigation ---
st.sidebar.title("Reach AI Navigation")
choice = st.sidebar.radio("ជំហានការងារ", ["Step 1: Transcribe", "Step 2: Dubbing"], index=st.session_state.current_step)

if choice == "Step 1: Transcribe": st.session_state.current_step = 0
else: st.session_state.current_step = 1

# --- ៥. STEP 1: TRANSCRIBE ---
if st.session_state.current_step == 0:
    st.header("🎙️ Step 1: Video to SRT")
    video_file = st.file_uploader("Upload Video", type=["mp4", "mov", "mp3"])
    
    if st.button("🚀 ចាប់ផ្ដើម Transcribe", type="primary"):
        if video_file:
            with st.spinner("កំពុងដំណើរការ..."):
                # រក្សាទុកជា temp.mp4 ឱ្យត្រូវតាម Error របស់បង
                with open("temp.mp4", "wb") as f:
                    f.write(video_file.getbuffer())
                
                model = whisper.load_model("tiny")
                res = model.transcribe("temp.mp4")
                
                srt_out = ""
                for i, s in enumerate(res['segments']):
                    srt_out += f"{i+1}\n{format_time(s['start'])} --> {format_time(s['end'])}\n{s['text'].strip()}\n\n"
                
                st.session_state.generated_srt = srt_out
                if os.path.exists("temp.mp4"): os.remove("temp.mp4")
                st.success("រួចរាល់!")

    if st.session_state.get('generated_srt'):
        st.text_area("លទ្ធផល SRT", st.session_state.generated_srt, height=250)
        if st.button("បន្តទៅ Step 2 ➡️", type="primary"):
            st.session_state.current_step = 1
            st.rerun()

# --- ៦. STEP 2: DUBBING ---
else:
    st.header("🎬 Step 2: AI Dubbing")
    srt_input = st.session_state.get('generated_srt', "")
    
    if not srt_input:
        st.warning("សូមធ្វើ Step 1 សិន!")
        if st.button("⬅️ ត្រលប់ទៅ Step 1"):
            st.session_state.current_step = 0
            st.rerun()
    else:
        if 'data' not in st.session_state:
            if st.button("📥 ចាប់ផ្ដើមបកប្រែ"):
                subs = list(srt.parse(srt_input))
                tr = GoogleTranslator(source='auto', target='km')
                data = []
                p = st.empty()
                for i, s in enumerate(subs):
                    p.write(f"បកប្រែឃ្លាទី {i+1}...")
                    data.append({"ID": i, "Khmer_Text": tr.translate(s.content), "Voice": "Male", "Start": s.start, "End": s.end})
                st.session_state.data = data
                st.rerun()

        if st.session_state.get('data'):
            df = pd.DataFrame(st.session_state.data)
            edited_df = st.data_editor(df, use_container_width=True, hide_index=True)
            
            if st.button("💾 Save Changes"):
                st.session_state.data = edited_df.to_dict('records')
                st.success("រក្សាទុកជោគជ័យ!")

            if st.button("🚀 ផលិត MP3 (Start Dubbing)", type="primary"):
                stat, pb = st.empty(), st.progress(0)
                final_audio = asyncio.run(generate_voice(st.session_state.data, 0, stat, pb))
                final_audio.export("final_dub.mp3", format="mp3")
                with open("final_dub.mp3", "rb") as f:
                    st.session_state.audio_bytes = f.read()
                st.success("រួចរាល់!")

            if st.session_state.get('audio_bytes'):
                st.audio(st.session_state.audio_bytes)
                st.download_button("📥 ទាញយក MP3", st.session_state.audio_bytes, "reach_dub.mp3")

            if st.button("⬅️ ត្រលប់ក្រោយ"):
                st.session_state.current_step = 0
                st.rerun()
