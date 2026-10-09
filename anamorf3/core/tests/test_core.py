import hashlib
import json
import logging
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from anamorf3.contracts import ChatChunk, CancelToken, EventBus, ToolResult, ToolStatus
from anamorf3.core import Core, Registry, Tool, ToolContext, Store
from anamorf3.core.workspace import path_in, register_workspace

class ScriptedModel:
    def __init__(self, responses): self.responses=list(responses); self.requests=[]
    def chat(self,req,cancel):
        self.requests.append(req)
        yield from self.responses.pop(0)
    def status(self): return {'ready':True,'model':'scripted-test'}

def call(name,args,cid='c1'):
    return {'id':cid,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.project=self.root/'project'; self.project.mkdir()
        self.cores=[]; logging.disable(logging.CRITICAL)
    def tearDown(self):
        for core in self.cores: core.close()
        self.tmp.cleanup(); logging.disable(logging.NOTSET)
    def core(self,responses):
        core=Core(ScriptedModel(responses),self.root/f'state{len(self.cores)}.sqlite')
        self.cores.append(core); sid=core.store.session(self.project)['id']; return core,sid

    def test_mode_forwarding_and_durable_history(self):
        for mode in ('local','cloud','auto'):
            core,sid=self.core([[ChatChunk(text='Привет',done=True,model='actual')]])
            task=core.submit(sid,'hello',mode,background=False)
            self.assertEqual(task['state'],'done'); self.assertEqual(core.model.requests[0].mode,mode)
            self.assertEqual(Store(core.store.path).history(sid)[-1]['content'],'Привет')
            events=core.store.events(task_id=task['id']); self.assertEqual(events[-1]['data']['model'],'actual')

    def test_tool_results_return_to_model_and_event_journal(self):
        (self.project/'a.txt').write_text('hello',encoding='utf-8')
        core,sid=self.core([[ChatChunk(tool_calls=[call('file_read',{'path':'a.txt'})],done=True)],
                           [ChatChunk(text='Read',done=True)]])
        task=core.submit(sid,'read',background=False)
        self.assertEqual(task['state'],'done')
        tool=core.model.requests[1].messages[-1]; result=json.loads(tool['content'])
        self.assertEqual(result['evidence']['sha256'],hashlib.sha256(b'hello').hexdigest())
        self.assertIn('tool.result',[e['type'] for e in core.store.events(task_id=task['id'])])

    def test_invalid_json_is_not_executed(self):
        c=call('file_create',{}); c['function']['arguments']='{broken'
        core,sid=self.core([[ChatChunk(tool_calls=[c],done=True)],[ChatChunk(text='Bad args',done=True)]])
        task=core.submit(sid,'write',background=False)
        self.assertEqual(task['state'],'done'); self.assertEqual(list(self.project.iterdir()),[])
        self.assertEqual(json.loads(core.model.requests[1].messages[-1]['content'])['status'],'failed')

    def test_empty_or_truncated_stream_is_failed(self):
        for response in ([],[ChatChunk(text='partial')],[ChatChunk(done=True)]):
            core,sid=self.core([response]); task=core.submit(sid,'hi',background=False)
            self.assertEqual(task['state'],'failed'); self.assertEqual(core.store.history(sid),[])

    def test_approval_is_exact_and_plan_resumes_once(self):
        core,sid=self.core([])
        task=core.prepare_plan(sid,'create',[{'name':'file_create','args':{'path':'a.txt','text':'new'}}])
        task=core.resume(task['id'],background=False); self.assertEqual(task['state'],'queued')
        self.assertFalse((self.project/'a.txt').exists())
        approval=core.store.events(task_id=task['id'])[-1]['data']['data']['approval_id']
        with self.assertRaises(ValueError): core.registry.approve(approval,'different-task')
        task=core.approve(task['id'],approval,background=False)
        self.assertEqual(task['state'],'done'); self.assertEqual((self.project/'a.txt').read_text(),'new')
        with self.assertRaises(ValueError): core.resume(task['id'],background=False)

    def test_failed_manual_plan_stops_before_next_action(self):
        core,sid=self.core([])
        task=core.prepare_plan(sid,'plan',[{'name':'file_read','args':{'path':'missing'}},{'name':'file_list','args':{}}])
        task=core.resume(task['id'],background=False)
        self.assertEqual(task['state'],'failed')
        calls=[e for e in core.store.events(task_id=task['id']) if e['type']=='tool.call']
        self.assertEqual(len(calls),1)

    def test_jobs_are_not_restarted_after_wait_timeout(self):
        core,sid=self.core([]); count=[]; gate=threading.Event()
        def slow(args,ctx):
            count.append(1); gate.wait(2); return ToolResult(ToolStatus.DONE,evidence={'completed':True})
        core.registry.register(Tool('slow','test',{'type':'object','additionalProperties':False},slow))
        ctx=ToolContext('t',self.project,CancelToken())
        a=core.registry.execute('slow',{},ctx,'same',wait=.001)
        b=core.registry.execute('slow',{},ctx,'same',wait=.001)
        self.assertEqual(a.status,ToolStatus.RUNNING); self.assertEqual(a.data,b.data)
        gate.set(); done=core.registry.execute('slow',{},ctx,'same',wait=2)
        self.assertTrue(done.ok); self.assertEqual(len(count),1)
        self.assertEqual(core.registry.execute('slow',{'x':1},ctx,'same').status,ToolStatus.FAILED)

    def test_schema_rejects_invalid_arguments(self):
        core,sid=self.core([]); ctx=ToolContext('t',self.project,CancelToken())
        for args in ([],{}, {'path':5}, {'path':'a','count':True}, {'path':'a','extra':'x'}, {'path':'a','count':10000}):
            r=core.registry.execute('file_read',args,ctx,'bad')
            self.assertEqual(r.status,ToolStatus.FAILED)

    def test_workspace_escape_and_private_paths(self):
        for name in ('../escape','.git/config','secrets.json','.env','config.local.json'):
            with self.assertRaises(ValueError): path_in(self.project,name)

    def test_patch_rejects_stale_hash(self):
        from anamorf3.core.workspace import patch
        p=self.project/'a.txt'; p.write_text('old')
        ctx=ToolContext('t',self.project,CancelToken())
        with self.assertRaises(ValueError): patch({'path':'a.txt','old':'old','new':'new','sha256':'stale'},ctx)
        self.assertEqual(p.read_text(),'old')

    def test_cancelled_model_never_finishes_task(self):
        core,sid=self.core([])
        class CancelModel:
            def chat(self,req,cancel):
                cancel.cancel('test interruption'); yield ChatChunk(text='partial',done=True)
        core.model=CancelModel(); task=core.submit(sid,'hi',background=False)
        self.assertEqual(task['state'],'cancelled')
        self.assertNotIn('task.finished',[e['type'] for e in core.store.events(task_id=task['id'])])

    def test_duplicate_call_id_fails(self):
        c=call('file_list',{})
        core,sid=self.core([[ChatChunk(tool_calls=[c,c],done=True)]])
        task=core.submit(sid,'list',background=False); self.assertEqual(task['state'],'failed')
        self.assertFalse(any(e['type']=='tool.call' for e in core.store.events(task_id=task['id'])))

    def test_second_task_cannot_overlap_project(self):
        core,sid=self.core([]); gate=threading.Event()
        class WaitingModel:
            def chat(self,req,cancel):
                gate.wait(2); yield ChatChunk(text='ok',done=True)
        core.model=WaitingModel(); task=core.submit(sid,'hi')
        other=core.store.session(self.project)['id']
        try:
            with self.assertRaises(RuntimeError): core.submit(other,'hi')
        finally: gate.set(); core.wait(task['id'],3)

    def test_command_cancel_kills_real_child(self):
        from anamorf3.core.workspace import command
        token=CancelToken(); ctx=ToolContext('t',self.project,token); out=[]
        th=threading.Thread(target=lambda:out.append(command({'argv':[sys.executable,'-c','import time;time.sleep(30)']},ctx)))
        th.start(); time.sleep(.3); token.cancel('test'); th.join(5)
        self.assertFalse(th.is_alive()); self.assertEqual(out[0].status,ToolStatus.CANCELLED)
        self.assertIsNotNone(out[0].evidence['exit_code'])

    def test_restart_marks_interrupted_without_replaying(self):
        store=Store(self.root/'recover.sqlite'); sid=store.session(self.project)['id']
        task=store.create_task(sid,'action'); store.update(task['id'],state='running')
        core=Core(ScriptedModel([]),store.path); self.cores.append(core)
        self.assertEqual(core.store.task(task['id'])['state'],'failed'); self.assertEqual(core.model.requests,[])

    def test_session_isolation_and_event_cursor(self):
        core,sid=self.core([[ChatChunk(text='one',done=True)],[ChatChunk(text='two',done=True)]])
        core.submit(sid,'secret1',background=False)
        other=core.store.session(self.project)['id']; core.submit(other,'secret2',background=False)
        req=core.model.requests[-1]
        self.assertFalse(any('secret1' in str(m) for m in req.messages))
        events=core.store.events(); self.assertEqual(core.store.events(after=events[-1]['seq']),[])

if __name__=='__main__': unittest.main(verbosity=2)
