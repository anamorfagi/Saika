"""Workspace tools: bounded reads/search, optimistic patches, child cancellation."""
from __future__ import annotations
import difflib
import hashlib
import os
import subprocess
import tempfile
import time
from pathlib import Path
from anamorf3.contracts import ToolResult, ToolStatus
from .tools import Tool

def path_in(root, name):
    p=(root/str(name)).resolve()
    if not p.is_relative_to(root.resolve()): raise ValueError('path outside project')
    # Never expose git credentials, local secrets or dependency trees by default.
    if any(x.lower() in ('.git','node_modules','secrets.json','api_keys.json','api_keys.txt','config.local.json','config.json')
           or x.lower().startswith(('.venv','secrets.json.','api_keys.','config.local.json.','config.json.'))
           for x in p.relative_to(root).parts):
        raise ValueError('private/runtime path')
    if p.name.lower()=='.env' or p.name.lower().startswith('.env.'): raise ValueError('private environment file')
    return p

def sha(data): return hashlib.sha256(data).hexdigest()

def read_file(args,ctx):
    p=path_in(ctx.root,args['path'])
    if p.stat().st_size>1_000_000: raise ValueError('file too large; use line range')
    raw=p.read_bytes(); lines=raw.decode('utf-8').splitlines()
    start=args.get('start',1); count=args.get('count',200)
    return ToolResult(ToolStatus.DONE,text='\n'.join(f'{i+1}: {x}' for i,x in enumerate(lines[start-1:start-1+count],start-1)),
                      evidence={'path':str(p),'sha256':sha(raw),'lines':len(lines)})

def list_files(args,ctx):
    base=path_in(ctx.root,args.get('path','.'))
    rows=[]
    for p in sorted(base.iterdir(),key=lambda x:x.name.lower()):
        try: path_in(ctx.root,p.relative_to(ctx.root))
        except ValueError: continue
        rows.append({'path':str(p.relative_to(ctx.root)),'dir':p.is_dir(),'bytes':p.stat().st_size})
        if len(rows)>=500: break
    return ToolResult(ToolStatus.DONE,text=f'Найдено элементов: {len(rows)}.',data={'files':rows},evidence={'root':str(base),'count':len(rows)})

def search(args,ctx):
    matches=[]; visited=0
    # Literal text search avoids regex backtracking and protects latency.
    for folder,dirs,files in os.walk(ctx.root,followlinks=False):
        dirs[:]=[d for d in dirs if d not in ('.git','.venv','node_modules','__pycache__','models','logs','data') and not (Path(folder)/d).is_symlink()]
        for name in files:
            if ctx.cancel.cancelled: return ToolResult(ToolStatus.CANCELLED)
            visited+=1
            if visited>5000: break
            try:
                p=path_in(ctx.root,Path(folder,name).relative_to(ctx.root))
                if p.stat().st_size>500_000: continue
                content=p.read_text(encoding='utf-8')
            except (ValueError,UnicodeError,OSError): continue
            for i,line in enumerate(content.splitlines(),1):
                if args['text'] in line: matches.append({'path':str(p.relative_to(ctx.root)),'line':i,'text':line[:500]})
                if len(matches)>=100: break
            if len(matches)>=100: break
        if visited>5000 or len(matches)>=100: break
    return ToolResult(ToolStatus.DONE,text=str(matches),data={'matches':matches},evidence={'visited':visited,'matches':len(matches)})

def patch(args,ctx):
    p=path_in(ctx.root,args['path']); raw=p.read_bytes()
    if len(raw)>1_000_000: raise ValueError('file too large')
    if sha(raw)!=args['sha256']: raise ValueError('file changed since inspection; read again')
    before=raw.decode('utf-8')
    if not args['old'] or before.count(args['old'])!=1: raise ValueError('old text must match exactly once')
    after=before.replace(args['old'],args['new'],1)
    diff=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile=args['path'],tofile=args['path']))
    if ctx.cancel.cancelled: return ToolResult(ToolStatus.CANCELLED)
    fd,tmp=tempfile.mkstemp(prefix='.anamorf3-',dir=p.parent)
    try:
        with os.fdopen(fd,'wb') as f: f.write(after.encode('utf-8')); f.flush(); os.fsync(f.fileno())
        if ctx.cancel.cancelled: return ToolResult(ToolStatus.CANCELLED)
        # Check again immediately before replacement, including symlink changes.
        if path_in(ctx.root,args['path'])!=p or sha(p.read_bytes())!=args['sha256']: raise ValueError('concurrent edit')
        os.replace(tmp,p)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    return ToolResult(ToolStatus.DONE,text=diff[:12000],data={'diff':diff},evidence={'path':str(p),'sha256':sha(p.read_bytes())})

def create_file(args,ctx):
    p=path_in(ctx.root,args['path'])
    if ctx.cancel.cancelled: return ToolResult(ToolStatus.CANCELLED)
    # Exclusive creation is atomic: never overwrite an uninspected existing file.
    raw=args['text'].encode('utf-8')
    with p.open('xb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
    return ToolResult(ToolStatus.DONE,text='Файл создан.',evidence={'path':str(p),'bytes':len(raw),'sha256':sha(raw)})

def kill_child(proc):
    if proc.poll() is not None: return
    if os.name=='nt':
        subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,timeout=10,creationflags=0x08000000)
    else:
        import signal
        os.killpg(proc.pid,signal.SIGKILL)
    try: proc.wait(10)
    except subprocess.TimeoutExpired: proc.kill(); proc.wait(10)

def command(args,ctx):
    cwd=path_in(ctx.root,args.get('cwd','.'))
    argv=args['argv']; timeout=args.get('timeout',60)
    # This is explicit approved native execution, NOT an OS sandbox.
    # stdin closed prevents interactive commands from waiting for invisible input.
    start=time.monotonic()
    with tempfile.TemporaryFile() as log:
        proc=subprocess.Popen(argv,cwd=cwd,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
             shell=False,creationflags=0x08000200 if os.name=='nt' else 0,start_new_session=os.name!='nt')
        state=None
        try:
            while proc.poll() is None:
                if ctx.cancel.wait(.05): state=ToolStatus.CANCELLED; break
                if time.monotonic()-start>timeout: state=ToolStatus.FAILED; break
                if log.tell()>8_000_000: state=ToolStatus.FAILED; break
        finally:
            if proc.poll() is None: kill_child(proc)
        log.seek(0); text=log.read(40_000).decode('utf-8',errors='replace')
    evidence={'pid':proc.pid,'exit_code':proc.returncode,'argv':argv,'cwd':str(cwd)}
    state=state or (ToolStatus.DONE if proc.returncode==0 else ToolStatus.FAILED)
    return ToolResult(state,text=text,evidence=evidence,error='cancelled/limit/command failure' if state!=ToolStatus.DONE else None)

def object_schema(props,required): return {'type':'object','properties':props,'required':required,'additionalProperties':False}
def register_workspace(registry):
    string={'type':'string','maxLength':200_000}
    path={'type':'string','maxLength':4096}
    registry.register(Tool('file_read','Read UTF-8 file with line numbers and content hash.',object_schema({'path':path,'start':{'type':'integer','minimum':1},'count':{'type':'integer','minimum':1,'maximum':500}},['path']),read_file))
    registry.register(Tool('file_list','List a project directory.',object_schema({'path':path},[]),list_files))
    registry.register(Tool('file_search','Find literal text inside project source.',object_schema({'text':{'type':'string','maxLength':500}},['text']),search))
    registry.register(Tool('file_patch','Replace one exact block, using SHA256 from file_read; requires approval.',object_schema({'path':path,'sha256':{'type':'string','maxLength':64},'old':string,'new':string},['path','sha256','old','new']),patch,True))
    registry.register(Tool('file_create','Create a new UTF-8 file; never overwrite; requires approval.',object_schema({'path':path,'text':string},['path','text']),create_file,True))
    registry.register(Tool('command_run','Execute argv in project; requires explicit approval. Native process, not a sandbox.',object_schema({'argv':{'type':'array','items':{'type':'string','maxLength':8192},'maxItems':100},'cwd':path,'timeout':{'type':'integer','minimum':1,'maximum':300}},['argv']),command,True))
