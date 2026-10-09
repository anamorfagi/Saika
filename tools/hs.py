print({k:v for k,v in HEAR_STAT.items() if not isinstance(v,(list,dict))})
print("QUIET", QUIET.get("on"), "observe", dict(observe) if isinstance(observe, dict) else observe)
