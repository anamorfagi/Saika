"""Typed tools, strict input checks, exact approvals and observable jobs."""
from __future__ import annotations
import hashlib
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
from anamorf3.contracts import CancelToken, Event, ToolResult, ToolStatus

def validate(value, schema, path='$', depth=0):
    if depth>20: raise ValueError('arguments nested too deeply')
    types={'object':dict,'array':list,'string':str,'number':(int,float),'integer':int,'boolean':bool,'null':type(None)}
    kind=schema.get('type')
    if kind in types and (not isinstance(value,types[kind]) or kind in ('number','integer') and isinstance(value,bool)):
        raise ValueError(f'{path}: expected {kind}')
    if 'enum' in schema and value not in schema['enum']: raise ValueError(f'{path}: outside enum')
    if isinstance(value,dict):
        for key in schema.get('required',[]):
            if key not in value: raise ValueError(f'{path}.{key}: required')
        props=schema.get('properties',{})
        if schema.get('additionalProperties') is False and set(value)-set(props): raise ValueError(f'{path}: unexpected fields')
        for key, item in value.items():
            if key in props: validate(item,props[key],path+'.'+key,depth+1)
    if isinstance(value,list):
        if len(value)>schema.get('maxItems',1000): raise ValueError(f'{path}: too many items')
        for i,item in enumerate(value): validate(item,schema.get('items',{}),f'{path}[{i}]',depth+1)
    if isinstance(value,str) and len(value)>schema.get('maxLength',200_000): raise ValueError(f'{path}: too long')
    if isinstance(value,(int,float)) and not isinstance(value,bool):
        if value<schema.get('minimum',float('-inf')) or value>schema.get('maximum',float('inf')): raise ValueError(f'{path}: outside bounds')

def result_dict(result):
    d=asdict(result); d['status']=result.status.value; return d

@dataclass(frozen=True)
class ToolContext:
    task_id: str
    root: Path
    cancel: CancelToken

@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable
    approval: bool = False

class Registry:
    def __init__(self, bus, workers=4, recorder=None):
        self.bus=bus; self._tools={}; self._jobs={}; self._approvals={}; self._consumed=set()
        self._recorder=recorder
        self._lock=threading.RLock()
        self._pool=ThreadPoolExecutor(max_workers=workers,thread_name_prefix='anamorf3-tool')

    def register(self, tool):
        if tool.name in self._tools: raise ValueError('duplicate tool: '+tool.name)
        if tool.parameters.get('type')!='object': raise ValueError('tool requires object schema')
        self._tools[tool.name]=tool

    def schemas(self):
        return [{'type':'function','function':{'name':t.name,'description':t.description,'parameters':t.parameters}}
                for t in self._tools.values()]

    def _publish(self, ev):
        if self._recorder: self._recorder(ev)
        self.bus.publish(ev)

    def has_running(self, root):
        with self._lock:
            return any(j['root']==str(root) and not j['future'].done() for j in self._jobs.values())

    def approve(self, approval_id, task_id):
        with self._lock:
            row=self._approvals.get(approval_id)
            if row is None or row['task_id']!=task_id: raise ValueError('approval does not belong to this task')
            if row['expires']<time.monotonic(): raise ValueError('approval expired')
            row['allowed']=True

    def execute(self, name, args, ctx, call_id, wait=0.05):
        if name not in self._tools: return ToolResult(ToolStatus.FAILED,error='unknown tool: '+name)
        tool=self._tools[name]
        try:
            validate(args,tool.parameters)
            signature=hashlib.sha256(json.dumps([name,args],ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
        except (ValueError,TypeError) as e: return ToolResult(ToolStatus.FAILED,error=str(e))
        key=(ctx.task_id,call_id)
        with self._lock:
            if key in self._jobs:
                job=self._jobs[key]
                if job['signature']!=signature: return ToolResult(ToolStatus.FAILED,error='call id reused with different arguments')
            else:
                if ctx.cancel.cancelled: return ToolResult(ToolStatus.CANCELLED,text=ctx.cancel.reason)
                if tool.approval:
                    aid=hashlib.sha256((ctx.task_id+call_id+signature).encode()).hexdigest()
                    row=self._approvals.get(aid)
                    if row is None or row['expires']<time.monotonic():
                        row={'task_id':ctx.task_id,'allowed':False,'expires':time.monotonic()+600}
                        self._approvals[aid]=row
                    if not row['allowed'] or aid in self._consumed:
                        return ToolResult(ToolStatus.NEEDS_CONFIRM,text='Требуется разрешение на конкретное действие.',
                                          data={'approval_id':aid,'tool':name,'args':args})
                    self._consumed.add(aid)
                jid=uuid.uuid4().hex
                self._publish(Event('tool.call','core',{'name':name,'args':args,'job_id':jid},ctx.task_id))
                def invoke():
                    start=time.monotonic()
                    try:
                        if ctx.cancel.cancelled: r=ToolResult(ToolStatus.CANCELLED,text=ctx.cancel.reason)
                        else: r=tool.handler(args,ctx)
                        if not isinstance(r,ToolResult): raise TypeError('handler must return ToolResult')
                        if r.status==ToolStatus.DONE and not r.evidence: raise ValueError('DONE requires evidence')
                    except Exception as e: r=ToolResult(ToolStatus.FAILED,error=str(e))
                    r.ms=int((time.monotonic()-start)*1000)
                    self._publish(Event('tool.result','core',{'name':name,'job_id':jid,**result_dict(r)},ctx.task_id))
                    return r
                job={'signature':signature,'job_id':jid,'root':str(ctx.root),'future':self._pool.submit(invoke)}
                self._jobs[key]=job
        try: return job['future'].result(timeout=wait)
        except TimeoutError:
            return ToolResult(ToolStatus.RUNNING,text='Действие ещё выполняется. Повторный запуск запрещён.',data={'job_id':job['job_id']})

    def close(self):
        self._pool.shutdown(wait=True,cancel_futures=True)
