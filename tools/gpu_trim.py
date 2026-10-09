import gc, torch
G=lambda b: round(b/2**30,2)
st=torch.cuda.memory_stats()
print("before: alloc", G(st["allocated_bytes.all.current"]), "reserved", G(st["reserved_bytes.all.current"]), "inactive_split", G(st["inactive_split_bytes.all.current"]), "active", G(st["active_bytes.all.current"]))
gc.collect(); torch.cuda.synchronize(); torch.cuda.empty_cache()
st=torch.cuda.memory_stats()
print("after : alloc", G(st["allocated_bytes.all.current"]), "reserved", G(st["reserved_bytes.all.current"]), "inactive_split", G(st["inactive_split_bytes.all.current"]))
ss=torch.cuda.memory_snapshot()
for s in sorted(ss, key=lambda s:-s["total_size"])[:3]:
    states={}
    for b in s["blocks"]: states[b["state"]]=states.get(b["state"],0)+b["size"]
    print("  seg", s["total_size"]//2**20, "MB", {k:v//2**20 for k,v in states.items()}, "is_expandable", s.get("is_expandable"))
f,t=torch.cuda.mem_get_info(); print("device used", G(t-f))
