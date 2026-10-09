from anamorf.stt import dialog_llm as D
D._emit = broadcast_event
print("emit set", D._emit is not None)
