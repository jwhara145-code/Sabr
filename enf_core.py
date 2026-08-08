"""
enf_core.py — استخراج بصمة تردد الشبكة الكهربائية (ENF) من ملف صوتي.

الطريقة العلمية الحقيقية المستخدمة (وليست محاكاة):
1. تحميل الصوت وخفض معدل العينات (يكفي لتغطية النطاق حول 50 هرتز بدقة).
2. فلترة تمريرة نطاقية (Bandpass) حول التردد الاسمي (50 هرتز ± هامش صغير)
   لعزل "الطنين" الكهربائي عن بقية الصوت.
3. تحويل فورييه قصير المدى (STFT) بنوافذ زمنية طويلة نسبيًا (لزيادة
   الدقة الترددية) لتتبع أعلى قمة طاقة داخل النطاق مع الزمن.
4. الناتج: سلسلة زمنية لقيمة التردد الدقيقة كل بضع ثوانٍ — وهذه هي
   "بصمة ENF" التي تُقارَن بها التسجيلات.
"""

import numpy as np
import librosa
from scipy.signal import butter, filtfilt, stft


def _parabolic_interpolate(freqs_axis, magnitudes, peak_idx):
    """
    استيفاء تقاطعي (Parabolic Interpolation) حول قمة الطيف لتحسين دقة
    تقدير التردد إلى ما دون دقة الصندوق الترددي الخام لـ STFT — هذي
    الخطوة أساسية عمليًا لأن فروقات ENF الحقيقية (أجزاء من مئة هرتز)
    أدق بكثير من دقة FFT الخام.
    """
    if peak_idx <= 0 or peak_idx >= len(magnitudes) - 1:
        return freqs_axis[peak_idx]
    y_m1, y_0, y_p1 = magnitudes[peak_idx - 1], magnitudes[peak_idx], magnitudes[peak_idx + 1]
    denom = (y_m1 - 2 * y_0 + y_p1)
    if abs(denom) < 1e-12:
        return freqs_axis[peak_idx]
    p = 0.5 * (y_m1 - y_p1) / denom
    df = freqs_axis[1] - freqs_axis[0] if len(freqs_axis) > 1 else 0
    return freqs_axis[peak_idx] + p * df


def extract_enf(audio_path, nominal_freq=50.0, band=0.4, sr_target=1000,
                 window_seconds=10.0, overlap_ratio=0.9):
    """
    يستخرج منحنى ENF من ملف صوتي.

    المعاملات:
        audio_path: مسار الملف الصوتي (wav/mp3/...)
        nominal_freq: التردد الاسمي للشبكة (50 هرتز بالسعودية)
        band: نصف عرض نطاق الفلترة بالهرتز (± حول nominal_freq)
        sr_target: معدل العينات بعد إعادة التشكيل (1000 هرتز كافٍ وكفؤ)
        window_seconds: طول نافذة التحليل بالثواني (كلما زاد، زادت الدقة
            الترددية لكن قلّت الدقة الزمنية)
        overlap_ratio: نسبة التداخل بين النوافذ المتتالية

    يُرجع:
        times: مصفوفة الأزمنة (بالثواني من بداية الملف)
        freqs: مصفوفة قيم التردد المقابلة لكل زمن
    """
    y, sr = librosa.load(audio_path, sr=sr_target, mono=True)

    low = (nominal_freq - band) / (sr / 2)
    high = (nominal_freq + band) / (sr / 2)
    b, a = butter(4, [low, high], btype="band")
    filtered = filtfilt(b, a, y)

    nperseg = int(window_seconds * sr)
    noverlap = int(nperseg * overlap_ratio)

    f, t, Zxx = stft(filtered, fs=sr, nperseg=nperseg, noverlap=noverlap)

    band_mask = (f >= nominal_freq - band) & (f <= nominal_freq + band)
    band_indices = np.where(band_mask)[0]

    freqs_over_time = []
    for i in range(Zxx.shape[1]):
        full_mag = np.abs(Zxx[:, i])
        band_mag = full_mag[band_indices]
        if band_mag.sum() < 1e-9:
            freqs_over_time.append(nominal_freq)
            continue
        local_peak = int(np.argmax(band_mag))
        global_peak_idx = band_indices[local_peak]
        refined = _parabolic_interpolate(f, full_mag, global_peak_idx)
        freqs_over_time.append(refined)

    return t, np.array(freqs_over_time)


def find_best_match(reference_times, reference_freqs, query_freqs):
    """
    يبحث عن أفضل نقطة تطابق زمني لمنحنى query داخل الأرشيف المرجعي
    عبر الارتباط المتقاطع (Cross-Correlation).

    يُرجع: (index البداية بالأرشيف, درجة الثقة 0-1)
    """
    ref = np.asarray(reference_freqs) - np.mean(reference_freqs)
    qry = np.asarray(query_freqs) - np.mean(query_freqs)

    if len(qry) > len(ref):
        return None, 0.0

    correlation = np.correlate(ref, qry, mode="valid")
    norm = np.linalg.norm(qry) * np.array([
        np.linalg.norm(ref[i:i + len(qry)]) for i in range(len(correlation))
    ])
    norm[norm == 0] = 1e-9
    scores = correlation / norm

    best_i = int(np.argmax(scores))
    confidence = float(np.clip(scores[best_i], 0, 1))
    return best_i, confidence


def detect_jump(freqs, threshold_std=3.0):
    """
    يفحص منحنى ENF لمقطع مفرد بحثًا عن "قفزة" غير طبيعية تدل على
    قص أو دمج (تلاعب). يعتمد على الانحراف المعياري لفروقات القيم
    المتتالية — أي فرق أكبر من threshold_std أضعاف الانحراف المعياري
    يُعتبر مشبوهًا.

    يُرجع: index نقطة القفزة، أو None لو ما فيه قفزة مشبوهة
    """
    diffs = np.abs(np.diff(freqs))
    if len(diffs) < 3:
        return None
    mean_d, std_d = np.mean(diffs), np.std(diffs)
    if std_d < 1e-9:
        return None
    threshold = mean_d + threshold_std * std_d
    suspicious = np.where(diffs > threshold)[0]
    if len(suspicious) == 0:
        return None
    return int(suspicious[0]) + 1
