import streamlit as st
import whisper
import datetime
import asyncio, edge_tts, srt, os, re, pandas as pd
from pydub import AudioSegment
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

# --- ១. ការកំណត់ Page Config ---
st.set_page_config(page_title="Reach AI Master", layout="wide", initial_sidebar_state="expanded")

# --- ២. ប្រព័ន្ធ Login ---
USER_NAME = "admin"
USER_PASSWORD = "reachzano" # លេខសម្ងាត់បងគឺ reachzano

def login():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if not st.session_state.logged_in:
        st.markdown("<h2 style='text-align: center;'>🔐 សូមចូលប្រើប្រាស់ប្រព័ន្ធ</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            with st.form("login_form"):
                user = st.text_input("ឈ្មោះអ្នកប្រើ (Username)")
                pw = st.text_input("លេខសម្ងាត់ (Password)", type="password")
                if st.form_submit_button("ចូលប្រើ (Login)", use_container_width=True):
                    if user == USER_NAME and pw == USER_PASSWORD:
                        st.session_state.logged_in = True
                        st.rerun()
                    else:
                        st.error("ឈ្មោះ ឬ លេខសម្ងាត់មិនត្រឹមត្រូវ!")
        st.stop()

login()

# --- ចាប់ពីទីនេះទៅ គឺជាកូដ Dubbing និង Transcribe របស់បងដែលនៅសល់ទាំងអស់ ---
# (បងបន្តដាក់កូដ Helper Functions និង Navigation របស់បងចូលមក)

# --- ៣. Helper Functions (Shared Functions) ---
def format_time(seconds):
    td = datetime.timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = int((td.total_seconds() - total_seconds) * 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"

def localize_khmer(text):
    if not text: return ""
    slang_map = {
        r"តើ(.*)មែនទេ": r"\1មែនអត់?", r"តើ(.*)ឬទេ": r"\1អត់?", 
        r"អ្នក": "ឯង", r"បាទ": "ហ្នឹងហើយ", r"ចាស": "ចា៎",
        r"សម្លៀកបំពាក់": "ខោអាវ", r"តើមានរឿងអ្វី": "មានរឿងអីហ្នឹង?", r"មិនអីទេ": "អត់អីទេ"
    }
    for p, r in slang_map.items(): text = re.sub(p, r, text)
    return re.sub(r"^តើ\s*", "", text).strip()

def get_voice_auto(text):
    f_words = ["ចាស", "ចា៎", "អូន", "នាង", "ម៉ាក់", "យាយ", "មីង", "កញ្ញា", "ស្រី", "ប្រពន្ធ", "ភរិយា"]
    if any(w in str(text) for w in f_words): return "Female"
    return "Male"

async def process_audio(data, speed, status, progress):
    combined = AudioSegment.silent(duration=0)
    current_ms = 0
    for i, row in enumerate(data):
        progress.progress((i + 1) / len(data))
        status.markdown(f"**🎙️ ផលិតឃ្លាទី:** `{i+1}`")
        text, duration = str(row['Khmer_Text']).strip(), (row['End'] - row['Start']).total_seconds() * 1000
        start_ms = row['Start'].total_seconds() * 1000
        if start_ms > current_ms:
            combined += AudioSegment.silent(duration=start_ms - current_ms)
            current_ms = start_ms
        v = "km-KH-SreymomNeural" if row['Voice'] == "Female" else "km-KH-PisethNeural"
        tmp = f"t_{i}.mp3"
        await edge_tts.Communicate(text, v, rate=f"{speed+20:+}%").save(tmp)
        if os.path.exists(tmp):
            seg = AudioSegment.from_file(tmp)
            wav = f"t_{i}.wav"; seg.export(wav, format="wav")
            if len(seg) > duration > 0:
                stretch_audio(wav, f"s_{i}.wav", min(len(seg)/duration, 1.3))
                seg = AudioSegment.from_file(f"s_{i}.wav")
            combined += seg; current_ms += len(seg)
            for f in [tmp, wav, f"s_{i}.wav"]: 
                if os.path.exists(f): 
                    try: os.remove(f)
                    except: pass
    return combined

# --- ៤. ការគ្រប់គ្រងទំព័រ (Navigation) ---
st.sidebar.title("🚀 Reach AI Menu")
page = st.sidebar.radio("ជ្រើសរើសផ្នែក:", ["1. Transcribe (Video -> SRT)", "2. Dubbing (SRT -> Audio)"])

if st.sidebar.button("🔴 Logout"):
    st.session_state.logged_in = False
    st.rerun()

# --- ៥. ទំព័រទី ១: TRANSCRIBE ---
if page == "1. Transcribe (Video -> SRT)":
    st.header("🎙️ Step 1: បំប្លែងវីដេអូទៅជាអក្សរ (SRT)")

    # កំណត់ផ្ទុកទិន្នន័យក្នុង Session បើមិនទាន់មាន
    if 'generated_srt' not in st.session_state:
        st.session_state.generated_srt = ""

    video_file = st.file_uploader("Upload Video/Audio", type=["mp4", "mp3", "m4a", "wav"])
    
    col_btn1, col_btn2 = st.columns([1, 4])
    with col_btn1:
        start_transcribe = st.button("🚀 ចាប់ផ្តើមបំប្លែង", type="primary")
    with col_btn2:
        if st.button("🗑️ លុបទិន្នន័យចោល (Clear)"):
            st.session_state.generated_srt = ""
            st.rerun()

    if video_file and start_transcribe:
        with st.spinner("AI កំពុងស្ដាប់... សូមរង់ចាំ (កុំបិទទំព័រនេះ)"):
            try:
                with open("temp_v.mp4", "wb") as f: 
                    f.write(video_file.getbuffer())
                model = whisper.load_model("base")
                result = model.transcribe("temp_v.mp4")
                
                srt_final = ""
                for i, seg in enumerate(result['segments']):
                    srt_final += f"{i+1}\n{format_time(seg['start'])} --> {format_time(seg['end'])}\n{seg['text'].strip()}\n\n"
                
                st.session_state.generated_srt = srt_final 
                st.success("✅ បំប្លែងរួចរាល់!")
            except Exception as e:
                st.error(f"កំហុសបច្ចេកទេស: {e}")

    # បង្ហាញលទ្ធផលឱ្យនៅជាប់រហូត (ទោះប្តូរទំព័រចុះឡើង)
    if st.session_state.generated_srt:
        st.divider()
        st.subheader("📄 លទ្ធផលដែលបានរក្សាទុក៖")
        st.text_area("SRT Content:", st.session_state.generated_srt, height=300)

# --- ៦. ទំព័រទី ២: DUBBING ---
elif page == "2. Dubbing (SRT -> Audio)":
    st.header("🎬 Step 2: ផលិតសម្លេងបកប្រែខ្មែរ")
    
    # ឆែកទិន្នន័យពីទំព័រទី១
    srt_data = st.session_state.get('generated_srt', "")
    
    if not srt_data:
        file = st.file_uploader("សូមបង្ហោះ File .srt (ឬទៅបំប្លែងនៅ Step 1 ជាមុនសិន)", type=["srt"])
        if file: srt_data = file.getvalue().decode("utf-8")
    else:
        st.success("✅ ទទួលបានទិន្នន័យពី Step 1 រួចជាស្រេច!")
        if st.button("🔄 ចាប់ផ្ដើមបកប្រែទិន្នន័យនេះ", type="primary"):
            subs = list(srt.parse(srt_data))
            tr_en, tr_km = GoogleTranslator(source='auto', target='en'), GoogleTranslator(source='en', target='km')
            data = []
            p = st.progress(0)
            for i, s in enumerate(subs):
                en = tr_en.translate(s.content)
                km = localize_khmer(tr_km.translate(en))
                data.append({"ID": i, "Select": False, "Original": s.content, "English": en, "Khmer_Text": km, "Voice": get_voice_auto(km), "Start": s.start, "End": s.end})
                p.progress((i+1)/len(subs))
            st.session_state.data = data
            st.rerun()

    # បង្ហាញតារាង Editor និងប៊ូតុងបញ្ជា (កូដបង)
    if st.session_state.get('data'):
        df = pd.DataFrame(st.session_state.data)
        
        # Sidebar Settings សម្រាប់ Dubbing
        with st.sidebar:
            st.divider()
            st.header("⚙️ Dubbing Settings")
            speed = st.slider("ល្បឿនសម្លេង AI (%)", -50, 50, 15)
            bgm = st.file_uploader("ភ្លេងផ្ទៃក្រោយ (BGM)", type=["mp3"])
            vol = st.slider("កម្រិតសម្លេង BGM", 0, 100, 15)

        # ប៊ូតុងបញ្ជាភេទ (ស្រីទាំងអស់ / ប្រុសទាំងអស់ / រើសតាម Select)
        c1, c2, c3, c4, c5 = st.columns([1,1,1,1,1.5])
        with c1:
            if st.button("👩 ស្រី (រើស)"):
                edited_rows = st.session_state.get("stable_editor", {}).get("edited_rows", {})
                for idx, val in edited_rows.items():
                    if val.get("Select") or df.iloc[idx]["Select"]: df.at[idx, "Voice"] = "Female"
                st.session_state.data = df.to_dict('records'); st.rerun()
        with c2:
            if st.button("👨 ប្រុស (រើស)"):
                edited_rows = st.session_state.get("stable_editor", {}).get("edited_rows", {})
                for idx, val in edited_rows.items():
                    if val.get("Select") or df.iloc[idx]["Select"]: df.at[idx, "Voice"] = "Male"
                st.session_state.data = df.to_dict('records'); st.rerun()
        with c3:
            if st.button("💃 ស្រីទាំងអស់"):
                df['Voice'] = 'Female'; st.session_state.data = df.to_dict('records'); st.rerun()
        with c4:
            if st.button("👔 ប្រុសទាំងអស់"):
                df['Voice'] = 'Male'; st.session_state.data = df.to_dict('records'); st.rerun()
        with c5:
            if st.button("♻️ Fix Selected"):
                tr_km_fix = GoogleTranslator(source='en', target='km')
                for idx, row in df.iterrows():
                    if row['Select']: df.at[idx, 'Khmer_Text'] = localize_khmer(tr_km_fix.translate(row['English']))
                st.session_state.data = df.to_dict('records'); st.rerun()

        # តារាង Editor
        edited_df = st.data_editor(
            df, key="stable_editor", use_container_width=True, hide_index=True,
            column_config={
                "ID": None, "Start": None, "End": None,
                "Select": st.column_config.CheckboxColumn("✔", default=False),
                "Original": st.column_config.TextColumn("Original", disabled=True),
                "English": st.column_config.TextColumn("English Ref"),
                "Khmer_Text": st.column_config.TextColumn("Khmer (កែនៅទីនេះ)", width="large"),
                "Voice": st.column_config.SelectboxColumn("ភេទ", options=["Male", "Female"])
            }
        )

        if st.button("💾 រក្សាទុកការកែ", type="secondary", use_container_width=True):
            st.session_state.data = edited_df.to_dict('records'); st.success("រក្សាទុកហើយ!")

        if st.button("🚀 ផលិតសម្លេង (Dub Now)", use_container_width=True, type="primary"):
            stat = st.empty(); pb = st.progress(0)
            try:
                res = asyncio.run(process_audio(st.session_state.data, speed, stat, pb))
                if bgm:
                    b_s = AudioSegment.from_file(bgm) - (60 - (vol * 0.6))
                    if len(b_s) < len(res): b_s = b_s * (int(len(res)/len(b_s)) + 1)
                    res = res.overlay(b_s[:len(res)])
                res.export("out.mp3", format="mp3")
                with open("out.mp3", "rb") as f: st.session_state.audio = f.read()
                st.success("ផលិតរួចរាល់!")
            except Exception as e: st.error(f"Error: {e}")

        if st.session_state.get('audio'):
            st.audio(st.session_state.audio)
            st.download_button("📥 ទាញយក MP3", st.session_state.audio, "dub_final.mp3", use_container_width=True)
