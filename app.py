# --- កូដសម្រាប់បន្លំ System ឱ្យស្គាល់ audioop ក្នុង Python 3.14 ---
try:
    import audioop
except ImportError:
    import audioop_lts as audioop
    import sys
    sys.modules['audioop'] = audioop

import streamlit as st
import whisper
import datetime
import asyncio, edge_tts, srt, os, re, pandas as pd
from pydub import AudioSegment
from deep_translator import GoogleTranslator
from audiostretchy.stretch import stretch_audio

# --- ១. កំណត់ Page Config ---
st.set_page_config(page_title="Reach AI Pro", layout="wide")

# បន្ថែម CSS ដើម្បីឱ្យប៊ូតុងធំៗស្រួលចុចលើទូរស័ព្ទ
st.markdown("""
    <style>
    .stButton>button { width: 100%; border-radius: 8px; height: 3em; }
    .stDownloadButton>button { width: 100%; border-radius: 8px; }
    @media (max-width: 600px) {
        .main .block-container { padding: 10px; }
    }
    </style>
    """, unsafe_allow_html=True)

# --- ២. ប្រព័ន្ធ Login ---
USER_NAME = "admin"
USER_PASSWORD = "reachzano" 

def login():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if not st.session_state.logged_in:
        st.markdown("<h2 style='text-align: center;'>🔐 សូមចូលប្រើប្រាស់</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            user = st.text_input("Username")
            pw = st.text_input("Password", type="password")
            if st.button("ចូលប្រើ"):
                if user == USER_NAME and pw == USER_PASSWORD:
                    st.session_state.logged_in = True
                    st.rerun()
                else:
                    st.error("ខុសលេខសម្ងាត់!")
        st.stop()

login()

# --- ៣. Helper Functions ---
def format_time(seconds):
    td = datetime.timedelta(seconds=seconds)
    return str(td)[:-3].replace(".", ",") if "." in str(td) else str(td) + ",000"

def localize_khmer(text):
    if not text: return ""
    slang_map = {r"តើ(.*)មែនទេ": r"\1មែនអត់?", r"អ្នក": "ឯង", r"បាទ": "បាទបង", r"ចាស": "ចា៎"}
    for p, r in slang_map.items(): text = re.sub(p, r, text)
    return text.strip()

async def process_audio(data, speed, status, progress):
    combined = AudioSegment.silent(duration=0)
    current_ms = 0
    for i, row in enumerate(data):
        progress.progress((i + 1) / len(data))
        status.write(f"🎙️ កំពុងផលិតឃ្លាទី {i+1}...")
        text = str(row['Khmer_Text']).strip()
        start_ms = row['Start'].total_seconds() * 1000
        duration = (row['End'] - row['Start']).total_seconds() * 1000
        
        if start_ms > current_ms:
            combined += AudioSegment.silent(duration=start_ms - current_ms)
            current_ms = start_ms
            
        v = "km-KH-SreymomNeural" if row['Voice'] == "Female" else "km-KH-PisethNeural"
        tmp = f"t_{i}.mp3"
        await edge_tts.Communicate(text, v, rate=f"{speed+20:+}%").save(tmp)
        
        if os.path.exists(tmp):
            seg = AudioSegment.from_file(tmp)
            if len(seg) > duration > 0:
                wav = f"t_{i}.wav"; seg.export(wav, format="wav")
                stretch_audio(wav, f"s_{i}.wav", min(len(seg)/duration, 1.3))
                seg = AudioSegment.from_file(f"s_{i}.wav")
                if os.path.exists(wav): os.remove(wav)
                if os.path.exists(f"s_{i}.wav"): os.remove(f"s_{i}.wav")
            combined += seg; current_ms += len(seg)
            if os.path.exists(tmp): os.remove(tmp)
    return combined

# --- ៤. Navigation ---
menu = st.sidebar.selectbox("🏠 ម៉ឺនុយមេ", ["បំប្លែងវីដេអូ (Transcribe)", "បញ្ចូលសម្លេង (Dubbing)"])
if st.sidebar.button("🚪 Logout"):
    st.session_state.logged_in = False
    st.rerun()

# --- ៥. ទំព័រទី ១: TRANSCRIBE ---
if menu == "បំប្លែងវីដេអូ (Transcribe)":
    st.title("🎙️ Step 1: Video to SRT")
    if 'generated_srt' not in st.session_state: st.session_state.generated_srt = ""

    video_file = st.file_uploader("ជ្រើសរើសវីដេអូ", type=["mp4", "mp3", "mov", "m4a"])
    
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🚀 ចាប់ផ្ដើមបំប្លែង", type="primary"):
            if video_file:
                with st.spinner("កំពុងស្តាប់ និងសរសេរ..."):
                    with open("temp.mp4", "wb") as f: f.write(video_file.getbuffer())
                    model = whisper.load_model("base")
                    res = model.transcribe("temp.mp4")
                    srt_out = ""
                    for i, s in enumerate(res['segments']):
                        srt_out += f"{i+1}\n{format_time(s['start'])} --> {format_time(s['end'])}\n{s['text'].strip()}\n\n"
                    st.session_state.generated_srt = srt_out
                    st.success("រួចរាល់! ទិន្នន័យត្រូវបានរក្សាទុក។")
    with c2:
        if st.button("🗑️ លុបទិន្នន័យ (Clear)"):
            st.session_state.generated_srt = ""; st.rerun()

    if st.session_state.generated_srt:
        st.text_area("លទ្ធផល SRT", st.session_state.generated_srt, height=300)
        st.info("👉 ទិន្នន័យត្រូវបានចងចាំក្នុងប្រព័ន្ធរួចហើយ។ សូមប្តូរទៅផ្នែក 'Dubbing' ដើម្បីបន្ត។")

# --- ៦. ទំព័រទី ២: DUBBING ---
else:
    st.title("🎬 Step 2: AI Dubbing")
    
    # ប៊ូតុងទាញទិន្នន័យពីទំព័រមុន
    srt_from_p1 = st.session_state.get('generated_srt', "")
    
    if srt_from_p1 and 'data' not in st.session_state:
        st.info("✅ ឃើញមានអត្ថបទ SRT ពី Step 1។")
        if st.button("📥 ប្រើអត្ថបទពី Step 1 ដើម្បីបកប្រែ"):
            subs = list(srt.parse(srt_from_p1))
            tr_en, tr_km = GoogleTranslator(source='auto', target='en'), GoogleTranslator(source='en', target='km')
            data = []
            p = st.empty()
            for i, s in enumerate(subs):
                p.write(f"បកប្រែឃ្លាទី {i+1}...")
                en = tr_en.translate(s.content)
                km = localize_khmer(tr_km.translate(en))
                data.append({"ID": i, "Select": False, "English": en, "Khmer_Text": km, "Voice": "Male", "Start": s.start, "End": s.end})
            st.session_state.data = data
            st.rerun()
    
    # បើគ្មានទិន្នន័យពី Step 1 ឱ្យ Upload ថ្មី
    if not srt_from_p1 and 'data' not in st.session_state:
        file = st.file_uploader("ឬ Upload File .srt ផ្ទាល់ខ្លួន", type=["srt"])
        if file:
            if st.button("បកប្រែអត្ថបទដែល Upload"):
                subs = list(srt.parse(file.getvalue().decode("utf-8")))
                tr_en, tr_km = GoogleTranslator(source='auto', target='en'), GoogleTranslator(source='en', target='km')
                data = []
                p = st.empty()
                for i, s in enumerate(subs):
                    p.write(f"បកប្រែឃ្លាទី {i+1}...")
                    en = tr_en.translate(s.content)
                    km = localize_khmer(tr_km.translate(en))
                    data.append({"ID": i, "Select": False, "English": en, "Khmer_Text": km, "Voice": "Male", "Start": s.start, "End": s.end})
                st.session_state.data = data
                st.rerun()

    # តំបន់គ្រប់គ្រងការ Dubbing
    if st.session_state.get('data'):
        df = pd.DataFrame(st.session_state.data)
        
        # បង្ហាញ Tabs ដើម្បីឱ្យស្រួលមើលលើទូរស័ព្ទ
        tab_edit, tab_setting, tab_process = st.tabs(["📝 កែអត្ថបទ", "⚙️ កំណត់សម្លេង", "🎵 ផលិត MP3"])
        
        with tab_edit:
            st.subheader("ផ្ទៀងផ្ទាត់អក្សរខ្មែរ")
            # ប៊ូតុងផ្លាស់ប្តូរភេទរហ័ស
            cx1, cx2 = st.columns(2)
            if cx1.button("👩 ស្រីទាំងអស់"): 
                df['Voice'] = 'Female'; st.session_state.data = df.to_dict('records'); st.rerun()
            if cx2.button("👨 ប្រុសទាំងអស់"): 
                df['Voice'] = 'Male'; st.session_state.data = df.to_dict('records'); st.rerun()
            
            # Editor
            edited_df = st.data_editor(df, use_container_width=True, hide_index=True,
                column_config={
                    "Select": st.column_config.CheckboxColumn("✔"),
                    "English": st.column_config.TextColumn("EN", disabled=True),
                    "Khmer_Text": st.column_config.TextColumn("KH (កែសម្រួល)", width="large"),
                    "Voice": st.column_config.SelectboxColumn("ភេទ", options=["Male", "Female"]),
                    "ID":None, "Start":None, "End":None
                })
            
            c_save, c_reset = st.columns(2)
            if c_save.button("💾 រក្សាទុកការកែ (Save)"):
                st.session_state.data = edited_df.to_dict('records'); st.success("រក្សាទុកជោគជ័យ!")
            if c_reset.button("🔴 Reset Project"):
                st.session_state.data = None; st.session_state.final_voice = None; st.rerun()

        with tab_setting:
            st.subheader("ការកំណត់សម្លេង")
            speed = st.slider("ល្បឿនសម្លេង AI (%)", -50, 50, 15)
            bgm_file = st.file_uploader("បន្ថែមភ្លេងផ្ទៃក្រោយ (BGM)", type=["mp3"])
            bgm_vol = st.slider("កម្រិតសម្លេង BGM", 0, 100, 20)

        with tab_process:
            st.subheader("ផលិត និងទាញយក")
            if st.button("🚀 ចាប់ផ្ដើមផលិតសម្លេង (START)", type="primary", use_container_width=True):
                stat = st.empty(); pb = st.progress(0)
                res_audio = asyncio.run(process_audio(st.session_state.data, speed, stat, pb))
                if bgm_file:
                    back = AudioSegment.from_file(bgm_file) - (60 - (bgm_vol * 0.6))
                    if len(back) < len(res_audio): back = back * (int(len(res_audio)/len(back)) + 1)
                    res_audio = res_audio.overlay(back[:len(res_audio)])
                res_audio.export("final.mp3", format="mp3")
                with open("final.mp3", "rb") as f: st.session_state.final_voice = f.read()
                st.success("ផលិតរួចរាល់!")
            
            if st.session_state.get('final_voice'):
                st.audio(st.session_state.final_voice)
                st.download_button("📥 ទាញយកលទ្ធផល (MP3)", st.session_state.final_voice, "dub_final.mp3")

# រក្សាសិទ្ធិដោយ Reach AI
