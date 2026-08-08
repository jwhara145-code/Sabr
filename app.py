import streamlit as st
import numpy as np
import pandas as pd
import tempfile
import os
import subprocess
import datetime

from enf_core import extract_enf, find_best_match, detect_jump
import db

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

try:
    total_points = db.archive_count()
    oldest, newest = db.archive_time_range()
    if total_points > 0:
        st.info(
            f"الأرشيف المرجعي الحالي: {total_points} نقطة محفوظة، "
            f"من {oldest.strftime('%Y-%m-%d %H:%M')} إلى {newest.strftime('%Y-%m-%d %H:%M')}"
        )
    else:
        st.warning("الأرشيف المرجعي فارغ حاليًا — ابدئي بإضافة أول تسجيل بالخطوة ١.")
    db_ready = True
except Exception:
    db_ready = False
    st.error(
        "قاعدة البيانات غير مهيَّأة بعد. أضيفي SUPABASE_URL وSUPABASE_KEY "
        "بإعدادات Secrets بمنصة Streamlit Cloud (راجعي README)."
    )

st.divider()

# ---------- Step 1: reference archive ----------
st.subheader("١. إضافة تسجيل مرجعي جديد للأرشيف")
st.write("ارفعي مقطع صوت من جهاز التسجيل المستمر، وحدّدي وقت بداية هذا المقطع فعليًا.")

col1, col2 = st.columns(2)
with col1:
    ref_date = st.date_input("تاريخ بداية التسجيل", value=datetime.date.today())
with col2:
    ref_time = st.time_input("وقت بداية التسجيل", value=datetime.time(0, 0))

ref_file = st.file_uploader("ملف الأرشيف المرجعي (wav/mp3)", type=["wav", "mp3", "m4a"], key="ref")

if ref_file is not None and st.button("استخراج وحفظ بالأرشيف الدائم", disabled=not db_ready):
    start_dt = datetime.datetime.combine(ref_date, ref_time)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        tmp.write(ref_file.read())
        ref_path = tmp.name
    with st.spinner("جاري استخراج بصمة ENF وحفظها بقاعدة البيانات الدائمة..."):
        t, f = extract_enf(ref_path)
        saved_count = db.save_reference_points(start_dt, t, f)
    os.unlink(ref_path)
    st.success(f"تم حفظ {saved_count} نقطة بشكل دائم بقاعدة البيانات — لن تُفقد حتى لو أُعيد تشغيل التطبيق.")
    st.line_chart(pd.DataFrame({"التردد (هرتز)": f}))

st.divider()

# ---------- Step 2: video/audio to verify ----------
st.subheader("٢. التسجيل المطلوب التحقق منه")
suspect_file = st.file_uploader("فيديو أو ملف صوتي للتحقق (mp4/wav/mp3)", type=["mp4", "wav", "mp3", "m4a"], key="suspect")

if suspect_file is not None and st.button("تحليل والتحقق من الأرشيف الدائم", disabled=not db_ready):
    archive_times, archive_freqs = db.load_reference_archive()

    if len(archive_freqs) == 0:
        st.error("الأرشيف المرجعي فارغ — أضيفي تسجيلًا مرجعيًا أولًا بالخطوة ١.")
    else:
        suffix = "." + suspect_file.name.split(".")[-1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(suspect_file.read())
            raw_path = tmp.name

        if suffix.lower() in [".mp4", ".mov", ".mkv"]:
            audio_path = raw_path + ".wav"
            subprocess.run(
                ["ffmpeg", "-y", "-i", raw_path, "-vn", "-acodec", "pcm_s16le", audio_path],
                capture_output=True,
            )
        else:
            audio_path = raw_path

        with st.spinner("جاري استخراج بصمة ENF ومقارنتها بالأرشيف الدائم..."):
            q_times, q_freqs = extract_enf(audio_path)

        st.line_chart(pd.DataFrame({"التردد (هرتز)": q_freqs}))

        jump_idx = detect_jump(q_freqs)

        if jump_idx is None:
            best_i, confidence = find_best_match(archive_times, archive_freqs, q_freqs)
            if best_i is not None and confidence > 0.3:
                matched_start = archive_times[best_i]
                matched_end = archive_times[min(best_i + len(q_freqs) - 1, len(archive_times) - 1)]
                st.success(
                    f"✅ التسجيل يبدو أصليًا — درجة الثقة: {confidence:.0%}\n\n"
                    f"الوقت المطابق بالأرشيف: من **{matched_start.strftime('%Y-%m-%d %H:%M:%S')}** "
                    f"إلى **{matched_end.strftime('%Y-%m-%d %H:%M:%S')}**"
                )
            else:
                st.warning(
                    "لم يُعثر على تطابق قوي بالأرشيف الحالي — "
                    "قد يكون التسجيل من فترة غير مغطاة بالأرشيف بعد، أو بعيدًا عن مصدر كهرباء."
                )
        else:
            part1 = q_freqs[:jump_idx]
            part2 = q_freqs[jump_idx:]
            i1, c1 = find_best_match(archive_times, archive_freqs, part1)
            i2, c2 = find_best_match(archive_times, archive_freqs, part2)

            msg = f"⚠️ تم اكتشاف تلاعب محتمل عند النقطة {jump_idx} من التسجيل.\n\n"
            if i1 is not None:
                t1_start = archive_times[i1]
                t1_end = archive_times[min(i1 + len(part1) - 1, len(archive_times) - 1)]
                msg += f"الجزء الأول يطابق: **{t1_start.strftime('%Y-%m-%d %H:%M:%S')} → {t1_end.strftime('%H:%M:%S')}** (ثقة {c1:.0%})\n\n"
            if i2 is not None:
                t2_start = archive_times[i2]
                msg += f"الجزء الثاني يطابق: بدايةً من **{t2_start.strftime('%Y-%m-%d %H:%M:%S')}** (ثقة {c2:.0%})\n\n"
            if i1 is not None and i2 is not None:
                gap = (t2_start - t1_end)
                msg += f"**الفترة المفقودة (المحذوفة/المدموجة): {gap}**"

            st.error(msg)

        os.unlink(raw_path)
        if audio_path != raw_path:
            os.unlink(audio_path)

st.divider()
st.caption("نموذج أولي شغّال يثبت المبدأ العلمي — وليس نظامًا معتمدًا رسميًا للاستخدام القضائي الفعلي بعد.")
