# Просодия из аудио: числа, из которых следователь берёт улики на mod.arousal.*, sp.pace, sp.emotional, dyn.*.peak
# [БЛОК 1] извлечение звука из mp4 → wav 16 кГц моно
import subprocess, json, sys, numpy as np, parselmouth, librosa
from parselmouth.praat import call
names=["Возраст","Как я остался без друга","Отношения"]
out={}
for n in names:
    src=f"/mnt/user-data/uploads/ГОЛОВНЫЕМЮСЛИ/#ГОЛОВНЫЕМЮСЛИ_ {n}.mp4"; wav=f"/home/claude/sk/{n}.wav"
    subprocess.run(["ffmpeg","-y","-loglevel","error","-i",src,"-ac","1","-ar","16000",wav],check=True)
    # [БЛОК 2] высота голоса (F0) по Praat: медиана, диапазон, изменчивость
    snd=parselmouth.Sound(wav); pitch=call(snd,"To Pitch",0.0,60,400)
    f0=pitch.selected_array["frequency"]; f0=f0[f0>0]
    # [БЛОК 3] паузы и темп: энергия по кадрам 50 мс, тишина = ниже порога дольше 0.25 с
    y,sr=librosa.load(wav,sr=16000); frame=int(.05*sr); hop=frame
    rms=librosa.feature.rms(y=y,frame_length=frame,hop_length=hop)[0]; thr=np.percentile(rms,20)*1.5
    voiced=rms>thr; t=np.arange(len(rms))*hop/sr
    pauses=[]; start=None
    for i,v in enumerate(voiced):
        if not v and start is None: start=t[i]
        if v and start is not None:
            d=t[i]-start
            if d>=.25: pauses.append(d)
            start=None
    speech_time=voiced.sum()*hop/sr; total=len(y)/sr
    # слоги ≈ пики огибающей энергии (Praat-подобный подсчёт через onset)
    onset=librosa.onset.onset_detect(y=y,sr=sr,hop_length=256,backtrack=False,units="time")
    # [БЛОК 4] громкость: динамика (дБ), доля громких кадров
    db=20*np.log10(rms[voiced]+1e-9);
    out[n]={"длительность_с":round(total,1),"речь_с":round(speech_time,1),"доля_речи":round(speech_time/total,2),
            "F0_медиана_Гц":round(float(np.median(f0)),1),"F0_размах_p10_p90_Гц":[round(float(np.percentile(f0,10)),1),round(float(np.percentile(f0,90)),1)],
            "F0_вариативность_полутонов":round(float(np.std(12*np.log2(f0/np.median(f0)))),2),
            "пауз_на_минуту":round(len(pauses)/(total/60),1),"пауза_медиана_с":round(float(np.median(pauses)) if pauses else 0,2),"пауза_p90_с":round(float(np.percentile(pauses,90)) if pauses else 0,2),"пауз_длиннее_1с":int(sum(p>1 for p in pauses)),
            "слогов_в_сек_речи":round(len(onset)/speech_time,2),"громкость_размах_дБ":round(float(np.percentile(db,95)-np.percentile(db,5)),1)}
    print(n,json.dumps(out[n],ensure_ascii=False))
json.dump(out,open("/home/claude/sk/prosody.json","w"),ensure_ascii=False,indent=1)
