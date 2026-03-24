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

# --- ១. កំណត់ Page Config & Gold Theme ---
st.set_page_config(page_title="Reach Maverick AI", layout="wide", page_icon="🎙️")

st.markdown("""
    <style>
    .stApp { background-color: #0E1117; }
    .gold-text {
        text-align: center;
        background: linear-gradient(90deg, #D4AF37, #F9E27E, #D4AF37);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-family: 'Kantumruy Pro', sans-serif;
        font-weight: 800;
        margin-bottom: 10px;
    }
    .stButton>button {
        background: linear-gradient(145deg, #D4AF37, #B8860B) !important;
        color: black !important;
        font-weight: bold !important;
        border-radius: 12px !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- ២. Engine Loading ---
@st.cache_resource
def load_whisper_engine():
    return whisper.load_model("tiny")

# --- ៣. Login System ---
USER_NAME = "admin"
USER_PASSWORD = "reachzano"

if "logged_in" not in st.session_state: st.session_state.logged_in = False
if "current_step" not in st.session_state: st.session_state.current_step = 0
if "generated_srt" not in st.session_state: st.session_state.generated_srt = ""

def login_system():
    u_val = st_javascript("localStorage.getItem('reach_user');")
    p_val = st_javascript("localStorage.getItem('reach_pw');")
    act_val = st_javascript("localStorage.getItem('last_active');")
    now_t = int(time.time())
    if act_val and str(u_val) == USER_NAME:
        if (now_t - int(act_val)) < 3600: st.session_state.logged_in = True
    if not st.session_state.logged_in:
        st.markdown("<h1 class='gold-text'>🎙️ REACH MAVERICK AI</h1>", unsafe_allow_html=True)
        u = st.text_input("👤 Username")
        p = st.text_input("🔑 Password", type="password")
        if st.button("SIGN IN"):
            if u == USER_NAME and p == USER_PASSWORD:
                st.session_state.logged_in = True
                st_javascript(f"localStorage.setItem('last_active', '{now_t}');")
                st.rerun()
        st.stop()
login_system()

# --- ៤. Helpers (Smart Khmer Formatting) ---
def format_time(seconds):
    td = datetime.timedelta(seconds=seconds)
    total_sec = int(td.total_seconds())
    milis = int((td.total_seconds() - total_sec) * 1000)
    return f"{total_sec // 3600:02}:{(total_sec % 3600) // 60:02}:{total_sec % 60:02},{milis:03}"

def clean_khmer_dub(text):
    """កែសម្រួលអត្ថបទបកប្រែឱ្យខ្លី និងងាយអានសម្រាប់ Dubbing"""
    if not text: return ""
    # កាត់ពាក្យដែល Google ចូលចិត្តថែម ហើយវែងពេក
    reps = {
        "តើអ្នកសុខសប្បាយទេ": "សុខសប្បាយអត់?",
        "តើមានអ្វីកើតឡើង": "មានរឿងអី?",
        "ខ្ញុំមិនដឹងទេ": "អត់ដឹងផង",
        "សូមអរគុណ": "អរគុណបង",
        "តើលោក": "បង/លោក",
        "របស់អ្នក": "ឯង/បង",
        "មែនទេ": "មែនអត់?",
        "បាទ": "បាទបង",
        "ចាស": "ចា៎",
        "យ៉ាងដូចម្តេច": "ម៉េចដែរ?"
    }
    for p, r in reps.items(): text = text.replace(p, r)
    # លុបចន្លោះទំនេរដែលដាច់ពាក្យចេញ
    text = re.sub(r'\s+', '', text)
    return text[:40] # កំណត់ឱ្យខ្លីបំផុត កុំឱ្យលើស ៤០ តួអក្សរក្នុងមួយឃ្លា

async def fetch_tts(row, idx, spd):
    v = "km-KH-SreymomNeural" if row['Voice'] == "Female" else "km-KH-PisethNeural"
    fn = f"s_{idx}.mp3"
    await edge_tts.Communicate(str(row['Khmer_Text']), v, rate=f"{spd:+}%").save(fn)
    return fn

# --- ៥. STEP 1: TRANSCRIBE & SMART FRAGMENT MERGE ---
if st.session_state.current_step == 0:
    st.markdown("<h2 class='gold-text'>🎙️ STEP 1: SMART TRANSCRIBE</h2>", unsafe_allow_html=True)
    f = st.file_uploader("Upload File", type=["mp4", "mp3", "mov", "m4a"])
    if st.button("🚀 START FAST TRANSCRIBE"):
        if f:
            with open("temp_raw", "wb") as file: file.write(f.getbuffer())
            with st.spinner("⚡ កំពុងរៀបចំអត្ថបទឱ្យខ្លីស្អាត..."):
                model = load_whisper_engine()
                res = model.transcribe("temp_raw", fp16=False)
                
                segs = res['segments']
                merged = []
                if segs:
                    curr = segs[0]
                    for i in range(1, len(segs)):
                        nxt = segs[i]
                        gap = nxt['start'] - curr['end']
                        # ផ្គួបឃ្លាដែលនៅជិតគ្នាខ្លាំង (Gap < 0.4s) កុំឱ្យដាច់ពាក្យ
                        if gap < 0.4 and len(curr['text'].split()) < 7: 
                            curr['text'] += nxt['text']
                            curr['end'] = nxt['end']
                        else:
                            merged.append(curr)
                            curr = nxt
                    merged.append(curr)

                srt_txt = ""
                for i, s in enumerate(merged):
                    srt_txt += f"{i+1}\n{format_time(s['start'])} --> {format_time(s['end'])}\n{s['text'].strip()}\n\n"
                st.session_state.generated_srt = srt_txt
                if os.path.exists("temp_raw"): os.remove("temp_raw")
                st.rerun()

    if st.session_state.generated_srt:
        st.text_area("SRT Result", st.session_state.generated_srt, height=250)
        if st.button("បន្តទៅ Dubbing ➡️"):
            st.session_state.current_step = 1; st.rerun()

# --- ៦. STEP 2: DUBBING (PERFECT SYNC & CLEAN KHMER) ---
else:
    st.markdown("<h2 class='gold-text'>🎬 STEP 2: AI DUBBING (SHORT & CLEAN)</h2>", unsafe_allow_html=True)
    if 'data' not in st.session_state:
        if st.button("📥 បកប្រែខ្មែរ (Version ខ្លីខ្លឹម)"):
            subs = list(srt.parse(st.session_state.generated_srt))
            with st.spinner("⏳ កំពុងសម្រាំងពាក្យខ្មែរ..."):
                texts = [s.content for s in subs]
                km_list = GoogleTranslator(source='auto', target='km').translate_batch(texts)
                # កែសម្រួលឱ្យខ្លីភ្លាមៗក្រោយបកប្រែ
                cleaned_km = [clean_khmer_dub(t) for t in km_list]
                
            st.session_state.data = [{"ID": i, "Select": False, "Khmer_Text": cleaned_km[i], "Voice": "Male", "Start": subs[i].start, "End": subs[i].end} for i in range(len(subs))]
            st.rerun()

    if st.session_state.get('data'):
        df = pd.DataFrame(st.session_state.data)
        edit_df = st.data_editor(df, use_container_width=True, hide_index=True, 
            column_config={"Khmer_Text": st.column_config.TextColumn("អត្ថបទខ្មែរ (កែឱ្យខ្លី)", width="large"), "Voice": st.column_config.SelectboxColumn("ភេទ", options=["Male", "Female"])})
        
        spd_val = st.slider("ល្បឿននិយាយ (%)", -50, 50, 5) # បន្ថែមល្បឿន ៥% ជា Default ឱ្យស្អាត
        
        if st.button("🚀 ផលិតសម្លេង Dubbing (ស្អាត & ត្រូវនាទី)", type="primary"):
            st.session_state.data = edit_df.to_dict('records')
            async def run_now():
                return await asyncio.gather(*[fetch_tts(r, i, spd_val) for i, r in enumerate(st.session_state.data)])
            
            with st.spinner("🎙️ កំពុងផលិតសម្លេងរលូន..."):
                f_list = asyncio.run(run_now())
                total_dur = int(st.session_state.data[-1]['End'].total_seconds() * 1000) + 2000
                final_audio = AudioSegment.silent(duration=total_dur, frame_rate=24000)
                
                for i, r in enumerate(st.session_state.data):
                    s_ms, e_ms = int(r['Start'].total_seconds() * 1000), int(r['End'].total_seconds() * 1000)
                    limit = e_ms - s_ms
                    if os.path.exists(f_list[i]):
                        seg = AudioSegment.from_file(f_list[i]).set_frame_rate(24000)
                        # បើនៅតែវែង ប្រើ Speedup ដើម្បីកុំឱ្យហៀរនាទី
                        if len(seg) > limit:
                            seg = speedup(seg, playback_speed=min(len(seg)/limit, 1.4), chunk_size=150, crossfade=25)
                            seg = seg[:limit]
                        
                        final_audio = final_audio.overlay(seg, position=s_ms)
                        os.remove(f_list[i])
                
                final_audio.export("final_reach.mp3", format="mp3")
                with open("final_reach.mp3", "rb") as file: 
                    st.session_state.audio_bytes = file.read()
            st.balloons()

        if st.session_state.get('audio_bytes'):
            st.audio(st.session_state.audio_bytes)
            st.download_button("📥 DOWNLOAD MP3", st.session_state.audio_bytes, "reach_maverick_perfect.mp3")

    st.button("⬅️ BACK", on_click=lambda: setattr(st.session_state, 'current_step', 0))
