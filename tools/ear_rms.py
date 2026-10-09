import numpy as np, inspect
from anamorf import hearing
b = hearing._buf
print("rms", hearing.STATE.get("rms"), "active", {k:(v["ru"],v["p"],round(__import__("time").time()-v["last"],1)) for k,v in hearing._active.items()}, "src", hearing.STATE.get("src"))
print("feed_sounds has gate:", "feed_min_rms" in inspect.getsource(hearing._feed_sounds)[:3000])
