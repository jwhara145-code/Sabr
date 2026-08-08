"""
db.py — طبقة قاعدة البيانات الدائمة (Supabase / PostgreSQL) لأرشيف بصمة ENF.

بدون هذي الطبقة، أي بيانات تُستخرج تضيع بمجرد إغلاق الصفحة أو نوم
التطبيق، لأن session_state بستريملت مؤقت فقط. هنا نخزّن كل نقطة (الوقت
الحقيقي بالتاريخ والساعة + قيمة التردد) بشكل دائم، بحيث الأرشيف يتراكم
عبر أيام وحتى لو أعيد تشغيل التطبيق من الصفر.
"""

import datetime
import streamlit as st
from supabase import create_client


@st.cache_resource
def get_client():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


def save_reference_points(start_time: datetime.datetime, rel_times, freqs):
    """يحفظ نقاط الأرشيف بالوقت الحقيقي (start_time + الزمن النسبي لكل نقطة)."""
    client = get_client()
    rows = []
    for rel_t, f in zip(rel_times, freqs):
        captured_at = start_time + datetime.timedelta(seconds=float(rel_t))
        rows.append({"captured_at": captured_at.isoformat(), "freq_hz": float(f)})

    batch_size = 500
    for i in range(0, len(rows), batch_size):
        client.table("enf_archive").insert(rows[i:i + batch_size]).execute()
    return len(rows)


def load_reference_archive():
    """يحمّل الأرشيف الكامل مرتّبًا زمنيًا: (قائمة أوقات حقيقية، قائمة ترددات)."""
    client = get_client()
    res = client.table("enf_archive").select("captured_at, freq_hz").order("captured_at").execute()
    data = res.data or []
    times = [datetime.datetime.fromisoformat(r["captured_at"]) for r in data]
    freqs = [r["freq_hz"] for r in data]
    return times, freqs


def archive_count():
    client = get_client()
    res = client.table("enf_archive").select("id", count="exact").execute()
    return res.count or 0


def archive_time_range():
    """يرجع (أقدم وقت، أحدث وقت) بالأرشيف، أو (None, None) لو فاضي."""
    times, _ = load_reference_archive()
    if not times:
        return None, None
    return min(times), max(times)

