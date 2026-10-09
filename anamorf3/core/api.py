"""Local HTTP adapter. Import Core without importing the old application."""
from __future__ import annotations
import argparse
import hmac
import importlib
import json
import logging
import mimetypes
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from .runner import Core

UI=Path(__file__).resolve().parent/'ui'

class UnconnectedModel:
    def chat(self,req,cancel):
        raise RuntimeError('ModelPort ещё не подключён. Ручные планы работают независимо от модели.')
        yield
    def status(self): return {'ready':False,'model':'','detail':'ModelPort not connected'}

def make_server(core,port=8785):
    access=secrets.token_urlsafe(32)
    origin='http://127.0.0.1:'+str(port)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def reply(self,status,data,content='application/json; charset=utf-8'):
            body=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type',content); self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers(); self.wfile.write(body)
        def authorized(self):
            host=self.headers.get('Host','')
            if host not in ('127.0.0.1:'+str(port),'localhost:'+str(port)): return False
            supplied=self.headers.get('Authorization','')
            if not hmac.compare_digest(supplied,'Bearer '+access): return False
            requested=self.headers.get('Origin')
            return requested is None or requested in (origin,'http://localhost:'+str(port))
        def do_GET(self):
            parsed=urlparse(self.path); path=parsed.path
            if path=='/healthz': return self.reply(200,{'ok':True,'version':'anamorf3-core'})
            if path in ('/','/app'):
                text=(UI/'index.html').read_text(encoding='utf-8').replace('__ACCESS_TOKEN__',access)
                return self.reply(200,text.encode(),'text/html; charset=utf-8')
            if path.startswith('/assets/'):
                target=(UI/path[1:]).resolve()
                if not target.is_relative_to((UI/'assets').resolve()) or not target.is_file(): return self.reply(404,{'error':'not found'})
                return self.reply(200,target.read_bytes(),mimetypes.guess_type(str(target))[0] or 'application/octet-stream')
            if not self.authorized(): return self.reply(403,{'error':'local session authorization required'})
            try:
                q=parse_qs(parsed.query)
                if path=='/api/status':
                    status=core.model.status()
                    safe={k:status[k] for k in ('ready','model','mode','detail') if k in status}
                    return self.reply(200,{'core':'ready','model':safe})
                if path=='/api/tools':
                    return self.reply(200,[dict(s,approval=core.registry._tools[s['function']['name']].approval) for s in core.registry.schemas()])
                if path=='/api/sessions':
                    with core.store.connect() as db: rows=db.execute('SELECT * FROM sessions ORDER BY created DESC LIMIT 100').fetchall()
                    return self.reply(200,[dict(r) for r in rows])
                if path=='/api/tasks':
                    sid=q.get('session_id',[''])[0]
                    with core.store.connect() as db: rows=db.execute('SELECT id FROM tasks WHERE session_id=? ORDER BY created DESC LIMIT 100',(sid,)).fetchall()
                    return self.reply(200,[core.store.task(r['id']) for r in rows])
                if path.startswith('/api/tasks/'): return self.reply(200,core.store.task(path.split('/')[-1]))
                if path=='/api/events': return self.reply(200,core.store.events(int(q.get('after',['0'])[0]),q.get('task_id',[None])[0]))
                return self.reply(404,{'error':'not found'})
            except (ValueError,KeyError) as e: return self.reply(400,{'error':str(e)})
            except Exception: logging.exception('GET failed'); return self.reply(500,{'error':'internal server error; see server log'})
        def do_POST(self):
            if not self.authorized(): return self.reply(403,{'error':'local session authorization required'})
            try:
                if not self.headers.get('Content-Type','').startswith('application/json'): raise ValueError('JSON required')
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=256_000: raise ValueError('invalid body length')
                data=json.loads(self.rfile.read(length)); path=urlparse(self.path).path
                if not isinstance(data,dict): raise ValueError('JSON object required')
                if path=='/api/sessions': return self.reply(201,core.store.session(data['root'],data.get('title','')))
                if path=='/api/plans': return self.reply(201,core.prepare_plan(data['session_id'],data.get('title','План'),data['steps']))
                if path=='/api/chat':
                    if not core.model.status().get('ready'): return self.reply(503,{'error':'Модель ещё не подключена. Доступны ручные планы.'})
                    return self.reply(202,core.submit(data['session_id'],data['text'],data.get('mode','auto')))
                parts=path.strip('/').split('/')
                if len(parts)==4 and parts[:2]==['api','tasks']:
                    tid,action=parts[2:]
                    if action=='run': return self.reply(202,core.resume(tid))
                    if action=='approve': return self.reply(202,core.approve(tid,data['approval_id']))
                    if action=='cancel': return self.reply(200,core.cancel(tid))
                return self.reply(404,{'error':'not found'})
            except (ValueError,KeyError,TypeError) as e: return self.reply(400,{'error':str(e)})
            except RuntimeError as e: return self.reply(409,{'error':str(e)})
            except Exception: logging.exception('POST failed'); return self.reply(500,{'error':'internal server error; see server log'})
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads=True
    return server

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8785)
    parser.add_argument('--db',default='data/anamorf3/state.sqlite')
    parser.add_argument('--model-factory',default='',help='Explicit resources.module:factory; core never starts a model itself')
    args=parser.parse_args(); logging.basicConfig(level=logging.INFO)
    model=UnconnectedModel()
    if args.model_factory:
        module,name=args.model_factory.split(':',1)
        if not module.startswith('anamorf3.resources'): raise ValueError('model factory must belong to resources')
        model=getattr(importlib.import_module(module),name)()
    core=Core(model,args.db); server=make_server(core,args.port)
    try:
        print('Anamorf3: http://127.0.0.1:'+str(args.port)+'/app',flush=True)
        server.serve_forever()
    finally: server.server_close(); core.close()

if __name__=='__main__': main()
