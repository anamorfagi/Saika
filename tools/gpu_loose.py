import gc, torch, collections
G=lambda b: round(b/2**30,2)
print("alloc", G(torch.cuda.memory_allocated()), "reserved", G(torch.cuda.memory_reserved()))
print("expandable:", torch.cuda.get_allocator_backend(), __import__("os").environ.get("PYTORCH_CUDA_ALLOC_CONF"), torch.__version__)
def _isM(o):
    try: return isinstance(o, torch.nn.Module)
    except Exception: return False
mods=[o for o in gc.get_objects() if _isM(o)]
print("GigaAMASR:", sum(1 for o in mods if type(o).__name__=="GigaAMASR"), "STTManagers:", sum(1 for o in gc.get_objects() if type(o).__name__=="STTManager"))
seen=set()
for m in mods:
    try:
        for t in list(m.parameters())+list(m.buffers()):
            if t.is_cuda: seen.add(t.data_ptr())
    except Exception: pass
# loose cuda tensors grouped by shape/dtype
agg=collections.Counter(); cnt=collections.Counter()
for o in gc.get_objects():
    try:
        if torch.is_tensor(o) and o.is_cuda and o.data_ptr() not in seen:
            seen.add(o.data_ptr()); k=(tuple(o.shape), str(o.dtype)); agg[k]+=o.numel()*o.element_size(); cnt[k]+=1
    except Exception: pass
tot=sum(agg.values()); print("loose total MB", tot//2**20)
for k,v in agg.most_common(12): print("  ", v//2**20, "MB x", cnt[k], k)
# allocator segments
try:
    ss=torch.cuda.memory_snapshot()
    segs=sorted(ss, key=lambda s:-s["total_size"])
    print("segments:", len(ss), "sum GB", G(sum(s["total_size"] for s in ss)))
    for s in segs[:8]:
        act=sum(b["size"] for b in s["blocks"] if b["state"]=="active_allocated")
        print("   seg", s["total_size"]//2**20, "MB active", act//2**20, "MB stream", s.get("stream"))
except Exception as e: print("snapshot", e)
