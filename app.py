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
from pydub.effects import speedup  # បន្ថែមការប្រើប្រាស់ speedup ឱ្យត្រូវតាមបច្ចេកទេស
from deep_translator import GoogleTranslator

# --- ១. កំណត់ Page Config ---
st.set_page_config(page_title="Reach AI Pro", layout="wide")

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
    total_sec = int(td.total_seconds())
    milis = int((td.total_seconds() - total_sec) * 1000)
    return f"{total_sec // 3600:02}:{(total_sec % 3600) // 60:02}:{total_sec % 60:02},{milis:03}"

def localize_khmer(text):
    if not text: return ""
    slang_map = {r"តើ(.*)មែនទេ": r"\1មែនអត់?", r"អ្នក": "ឯង", r"បាទ": "បាទបង", r"ចាស": "ចា៎"}
    for p, r in slang_map.items(): text = re.sub(p, r, text)
    return text.strip()

# មុខងារផលិតសម្លេងដែលមានភាពសុក្រិតខ្ពស់
async def process_audio(data, base_speed, status, progress):
    combined = AudioSegment.silent(duration=0)
    current_ms = 0
    
    for i, row in enumerate(data):
        progress.progress((i + 1) / len(data))
        status.write(f"🎙️ កំពុងផលិតឃ្លាទី {i+1}...")
        
        text = str(row['Khmer_Text']).strip()
        start_ms = int(row['Start'].total_seconds() * 1000)
        end_ms = int(row['End'].total_seconds() * 1000)
        duration_srt = end_ms - start_ms 
        
        # ១. បន្ថែមចន្លោះស្ងាត់ឱ្យបានសុក្រិតបំផុតតាមពេលវេលាចាប់ផ្ដើម
        if start_ms > current_ms:
            combined += AudioSegment.silent(duration=start_ms - current_ms)
            current_ms = start_ms

        # ២. ផលិតសម្លេងពី AI
        voice = "km-KH-SreymomNeural" if row['Voice'] == "Female" else "km-KH-PisethNeural"
        tmp_file = f"temp_{i}.mp3"
        await edge_tts.Communicate(text, voice, rate=f"{base_speed:+}%").save(tmp_file)
        
        if os.path.exists(tmp_file):
            seg = AudioSegment.from_file(tmp_file)
            
            # ៣. មួលល្បឿនដោយមិនឱ្យប្តូរ Pitch (សម្លេងមិនតូច) ប្រសិនបើសម្លេងវែងជាង Subtitle
            if len(seg) > duration_srt and duration_srt > 0:
                ratio = len(seg) / duration_srt
                # ប្រើ speedup ឱ្យបានត្រឹមត្រូវដើម្បីកុំឱ្យ Error
                seg = speedup(seg, playback_speed=min(ratio, 2.0), chunk_size=150, crossfade=25)
            
            # ៤. បង្ខំឱ្យបញ្ចប់ត្រឹមនាទីដែលកំណត់ (Sync 100%)
            seg = seg[:duration_srt]
            combined += seg
            current_ms += len(seg)
            
            try:
                os.remove(tmp_file)
            except: pass
            
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
                with st.spinner("កំពុងស្តាប់ និងរៀបចំឃ្លាឱ្យសមស្រប..."):
                    with open("temp.mp4", "wb") as f: f.write(video_file.getbuffer())
                    model = whisper.load_model("base")
                    res = model.transcribe("temp.mp4")
                    
                    # --- បច្ចេកទេសបញ្ចូលឃ្លាខ្លីៗឱ្យទៅជាវែង (Smart Merging) ---
                    # ជួយឱ្យ AI មានពេលនិយាយបានច្រើន និងមិនបាច់ប្រញាប់មួលសម្លេងឱ្យលឿនពេក
                    segments = res['segments']
                    merged = []
                    if segments:
                        curr = segments[0]
                        for next_seg in segments[1:]:
                            # បើឃ្លាមុនខ្លីជាង ២.៥ វិនាទី ឱ្យបូកចូលគ្នា
                            if (curr['end'] - curr['start']) < 2.5:
                                curr['end'] = next_seg['end']
                                curr['text'] += " " + next_seg['text']
                            else:
                                merged.append(curr)
                                curr = next_seg
                        merged.append(curr)
                    
                    srt_out = ""
                    for i, s in enumerate(merged):
                        srt_out += f"{i+1}\n{format_time(s['start'])} --> {format_time(s['end'])}\n{s['text'].strip()}\n\n"
                    st.session_state.generated_srt = srt_out
                    st.success("រួចរាល់!")
    with c2:
        if st.button("🗑️ លុបទិន្នន័យ (Clear)"):
            st.session_state.generated_srt = ""; st.rerun()

    if st.session_state.generated_srt:
        st.text_area("លទ្ធផល SRT", st.session_state.generated_srt, height=300)

# --- ៦. ទំព័រទី ២: DUBBING ---
else:
    st.title("🎬 Step 2: AI Dubbing")
    srt_from_p1 = st.session_state.get('generated_srt', "")
    
    if srt_from_p1 and 'data' not in st.session_state:
        if st.button("📥 ចាប់ផ្ដើមប្រើអត្ថបទពី Step 1"):
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

    if st.session_state.get('data'):
        df = pd.DataFrame(st.session_state.data)
        tab_edit, tab_setting, tab_process = st.tabs(["📝 កែអត្ថបទ", "⚙️ កំណត់សម្លេង", "🎵 ផលិត MP3"])
        
        with tab_edit:
            edited_df = st.data_editor(df, use_container_width=True, hide_index=True,
                column_config={
                    "Select": st.column_config.CheckboxColumn("✔"),
                    "English": st.column_config.TextColumn("EN", disabled=True),
                    "Khmer_Text": st.column_config.TextColumn("KH (កែសម្រួល)", width="large"),
                    "Voice": st.column_config.SelectboxColumn("ភេទ", options=["Male", "Female"]),
                    "ID":None, "Start":None, "End":None
                })
            if st.button("💾 រក្សាទុកការកែ (Save)"):
                st.session_state.data = edited_df.to_dict('records'); st.success("រក្សាទុកជោគជ័យ!")

        with tab_setting:
            speed = st.slider("ល្បឿនសម្លេងបន្ថែម (%)", -50, 50, 0)
            bgm_file = st.file_uploader("បន្ថែមភ្លេងផ្ទៃក្រោយ (BGM)", type=["mp3"])
            bgm_vol = st.slider("កម្រិតសម្លេង BGM", 0, 100, 20)

        with tab_process:
            if st.button("🚀 START DUBBING", type="primary"):
                stat = st.empty(); pb = st.progress(0)
                res_audio = asyncio.run(process_audio(st.session_state.data, speed, stat, pb))
                if bgm_file:
                    back = AudioSegment.from_file(bgm_file) - (60 - (bgm_vol * 0.6))
                    if len(back) < len(res_audio): back = back * (int(len(res_audio)/len(back)) + 1)
                    res_audio = res_audio.overlay(back[:len(res_audio)])
                res_audio.export("final.mp3", format="mp3")
                with open("final.mp3", "rb") as f: st.session_state.final_voice = f.read()
                st.success("រួចរាល់!")
            
            if st.session_state.get('final_voice'):
                st.audio(st.session_state.final_voice)
                st.download_button("📥 ទាញយកលទ្ធផល (MP3)", st.session_state.final_voice, "dub_final.mp3")
