import numpy as np
from anamorf import voiceprint as v
out=[]
for n,sp in v.S.reg.speakers.items():
    X=sp.get("embs")
    if X is None or len(X)<3: out.append(f"{n}: n={0 if X is None else len(X)}"); continue
    X=np.asarray(X,np.float32); X/= (np.linalg.norm(X,axis=1,keepdims=True)+1e-9); c=X.mean(0); c/=np.linalg.norm(c)+1e-9
    out.append(f"{n}: n={len(X)} dens={(X@c).mean():.2f}")
open(r"C:\AI\Saika\data\dens_state.txt","w",encoding="utf-8").write("\n".join(out))
