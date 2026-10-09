r = voiceprint.forget_all()
print("забыто:", len(r["forgotten"]), r["forgotten"][:30])
print("осталось голосов:", len(voiceprint.S.reg.speakers))
