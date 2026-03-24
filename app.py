try:
    def format_time(seconds):
    td = datetime.timedelta(seconds=seconds)
    total_sec = int(td.total_seconds())
    milis = int((td.total_seconds() - total_sec) * 1000)
    return f"{total_sec // 3600:02}:{(total_sec % 3600) // 60:02}:{total_sec % 60:02},{milis:03}"
    import audioop
except ImportError:
    try:
        import audioop_lts as audioop
        import sys
        sys.modules['audioop'] = audioop
    except ImportError:
        # បើនៅតែរកមិនឃើញទៀត វានឹងប្រាប់ឱ្យដឹង
        st.error("សូមថែម audioop-lts ក្នុង requirements.txt សិនបង Reach!")

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

# --- ២. Gemini API Configuration (Auto-Save & Status Check) ---
st.sidebar.markdown("### 🔑 API Configuration")
saved_key = st_javascript("localStorage.getItem('gemini_api_key');")

api_key_input = st.sidebar.text_input(
    "Gemini API Key", 
    value=saved_key if saved_key else "",
    type="password",
    help="ប្តូរលេខថ្មីនៅទីនេះពេលអស់ Free Tier"
)

def check_api_status(key):
    if not key: return False
    try:
        # បង្ខំឱ្យប្រើ API Key ថ្មី
        genai.configure(api_key=key)
        # ប្រើឈ្មោះម៉ូដែលខ្លី 'gemini-1.5-flash' 
        # ប្រសិនបើនៅតែ 404 បងសាកដូរទៅ 'gemini-pro' ដើម្បីតេស្តសិនក៏បាន
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # សាកល្បងហៅដោយមិនបញ្ជាក់ Version ច្រើនពេក
        response = model.generate_content("test", generation_config={"max_output_tokens": 1})
        return True
    except Exception as e:
        # បង្ហាញ Error ឱ្យចំថាបញ្ហាអី
        st.sidebar.error(f"Error: {str(e)}")
        return False

def gemini_refine_srt(raw_srt):
    if not st.session_state.get('api_ready'):
        return raw_srt
    
    # ប្រើ Prompt ឱ្យសាមញ្ញបំផុតសម្រាប់ Test
    prompt = f"Please clean up this SRT text for better flow in Khmer dubbing, keep timecodes: {raw_srt}"
    
    try:
        # បង្កើត Model Object ថ្មីរាល់ពេលហៅ
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        st.error(f"❌ Gemini Refine Error: {str(e)}")
        return raw_srt

def simplify_khmer(text):
    if not text: return ""
    reps = {"តើ(.*)មែនទេ": r"\1មែនអត់?", "របស់អ្នក": "ឯង", "បាទ": "បាទបង", "ចាស": "ចា៎"}
    for p, r in reps.items(): text = re.sub(p, r, text)
    return text.strip()

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

# --- ៤. Navigation Logic ---
if 'current_step' not in st.session_state: st.session_state.current_step = 0
step_options = ["បំប្លែងវីដេអូ (Transcribe)", "បញ្ចូលសម្លេង (Dubbing)"]
selected_step = st.sidebar.radio("ជំហានការងារ", step_options, index=st.session_state.current_step)
st.session_state.current_step = 0 if selected_step == step_options[0] else 1

# --- ៥. Step 0: TRANSCRIBE ---
if st.session_state.current_step == 0:
    st.title("🎙️ Step 1: Video to Smart SRT")
    video_file = st.file_uploader("ជ្រើសរើសវីដេអូ", type=["mp4", "mp3", "mov", "m4a"])
    
    if st.button("🚀 ចាប់ផ្ដើមបំប្លែង (Smart Mode)", type="primary", use_container_width=True):
        if video_file:
            with st.spinner("Whisper កំពុងបំប្លែង និង Gemini កំពុងសម្រួលអត្ថបទ..."):
                with open("temp.mp4", "wb") as f: f.write(video_file.getbuffer())
                model = whisper.load_model("tiny")
                res = model.transcribe("temp.mp4")
                
                raw_srt = ""
                for i, s in enumerate(res['segments']):
                    raw_srt += f"{i+1}\n{format_time(s['start'])} --> {format_time(s['end'])}\n{s['text'].strip()}\n\n"
                
                # ប្រើ Gemini សម្រួលអត្ថបទឱ្យស្អាត
                st.session_state.generated_srt = gemini_refine_srt(raw_srt)
                st.success("រួចរាល់!")
                if os.path.exists("temp.mp4"): os.remove("temp.mp4")

    if st.session_state.get('generated_srt'):
        st.text_area("លទ្ធផល SRT ពី Gemini", st.session_state.generated_srt, height=300)
        if st.button("បន្តទៅមុខ ➡️", type="primary", use_container_width=True):
            st.session_state.current_step = 1; st.rerun()

# --- ៦. Step 1: DUBBING ---
else:
    st.title("🎬 Step 2: AI Dubbing")
    srt_input = st.session_state.get('generated_srt', "")
    if not srt_input:
        st.warning("⚠️ សូមបំពេញ Step 1 សិន!")
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
                if st.button("💾 រក្សាទុក"):
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
        st.session_state.current_step = 0; st.rerun()
