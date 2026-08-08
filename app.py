import streamlit as st
import numpy as np
import pandas as pd
import tempfile
import os
import subprocess

from enf_core import extract_enf, find_best_match, detect_jump

st.set_page_config(page_title="سَبْر | Sabr", page_icon="🔎", layout="centered")

st.markdown(
    """
    <style>
    body, .stApp { background-color: #050a16; }
    h1, h2, h3, p, label, .stMarkdown { color: #eef2fa !important; }
    .stButton>button { background-color: #1f5fc4; color: white; border: none; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("سَبْر")
st.caption("منصة التحقق من صحة الأدلة الرقمية عبر بصمة الشبكة الكهربائية السعودية (ENF)")

st.divider()

# ---------- Step 1: reference archive ----------
st.subheader("١. الأرشيف المرجعي")
st.write("ارفعي تسجيل الصوت المستمر (الأرشيف المرجعي) المسجَّل بجهازكم.")
ref_file = st.file_uploader("ملف الأرشيف المرجعي (wav/mp3)", type=["wav", "mp3", "m4a"], key="ref")

if "ref_times" not in st.session_state:
    st.session_state.ref_times = None
    st.session_state.ref_freqs = None

if ref_file is not None and st.button("استخراج بصمة الأرشيف"):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        tmp.write(ref_file.read())
        ref_path = tmp.name
    with st.spinner("جاري استخراج بصمة ENF من الأرشيف..."):
        t, f = extract_enf(ref_path)
        st.session_state.ref_times = t
        st.session_state.ref_freqs = f
    os.unlink(ref_path)
    st.success(f"تم استخراج {len(st.session_state.ref_freqs)} نقطة تردد من الأرشيف.")
    st.line_chart(pd.DataFrame({"التردد (هرتز)": st.session_state.ref_freqs}))

st.divider()

# ---------- Step 2: video/audio to verify ----------
st.subheader("٢. التسجيل المطلوب التحقق منه")
suspect_file = st.file_uploader("فيديو أو ملف صوتي للتحقق (mp4/wav/mp3)", type=["mp4", "wav", "mp3", "m4a"], key="suspect")

if suspect_file is not None and st.button("تحليل والتحقق"):
    if st.session_state.ref_freqs is None:
        st.error("لازم تستخرجين بصمة الأرشيف المرجعي أولًا (الخطوة ١).")
    else:
        suffix = "." + suspect_file.name.split(".")[-1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(suspect_file.read())
            raw_path = tmp.name

        # extract audio if it's a video file
        if suffix.lower() in [".mp4", ".mov", ".mkv"]:
            audio_path = raw_path + ".wav"
            subprocess.run(
                ["ffmpeg", "-y", "-i", raw_path, "-vn", "-acodec", "pcm_s16le", audio_path],
                capture_output=True,
            )
        else:
            audio_path = raw_path

        with st.spinner("جاري استخراج بصمة ENF من التسجيل..."):
            q_times, q_freqs = extract_enf(audio_path)

        st.line_chart(pd.DataFrame({"التردد (هرتز)": q_freqs}))

        jump_idx = detect_jump(q_freqs)

        if jump_idx is None:
            best_i, confidence = find_best_match(
                st.session_state.ref_times, st.session_state.ref_freqs, q_freqs
            )
            if best_i is not None and confidence > 0.3:
                st.success(
                    f"✅ التسجيل يبدو أصليًا — درجة الثقة بالتطابق: {confidence:.0%}\n\n"
                    f"أقرب نقطة تطابق بالأرشيف: الفهرس {best_i}"
                )
            else:
                st.warning(
                    "لم يُعثر على تطابق قوي بالأرشيف الحالي — "
                    "قد يكون التسجيل من فترة غير مغطاة بالأرشيف، أو بعيدًا عن مصدر كهرباء."
                )
        else:
            part1 = q_freqs[:jump_idx]
            part2 = q_freqs[jump_idx:]
            i1, c1 = find_best_match(st.session_state.ref_times, st.session_state.ref_freqs, part1)
            i2, c2 = find_best_match(st.session_state.ref_times, st.session_state.ref_freqs, part2)
            st.error(
                f"⚠️ تم اكتشاف تلاعب محتمل عند النقطة {jump_idx} من التحليل.\n\n"
                f"الجزء الأول يطابق الأرشيف عند الفهرس {i1} (ثقة {c1:.0%})\n\n"
                f"الجزء الثاني يطابق الأرشيف عند الفهرس {i2} (ثقة {c2:.0%})\n\n"
                f"هذا يدل على احتمال وجود قص أو دمج بين الجزأين."
            )

        os.unlink(raw_path)
        if audio_path != raw_path:
            os.unlink(audio_path)

st.divider()
st.caption("نموذج أولي شغّال يثبت المبدأ العلمي — وليس نظامًا معتمدًا رسميًا للاستخدام القضائي الفعلي بعد.")
