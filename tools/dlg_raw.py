from anamorf.stt import dialog_llm as D
open(r"C:\AI\Saika\data\dlg_raw.txt","w",encoding="utf-8").write("IN:\n%s\n\nOUT:\n%s\n\nERR: %s" % (D.STATE.get("raw_in",""), D.STATE.get("raw",""), D.STATE.get("err","")))
