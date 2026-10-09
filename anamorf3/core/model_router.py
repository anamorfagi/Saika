"""Select explicit resources ports. No subprocesses or model lifecycles in core."""
from __future__ import annotations
from anamorf3.resources import make_port


class ModelRouter:
    def __init__(self, bus=None, default_mode='cloud'):
        if default_mode not in ('cloud', 'local'):
            raise ValueError('default_mode must be cloud or local')
        self.mode = default_mode
        self.ports = {mode: make_port(mode, bus) for mode in ('cloud', 'local')}

    def chat(self, req, cancel):
        mode = self.mode if req.mode == 'auto' else req.mode
        if mode not in self.ports:
            raise ValueError('unsupported model mode')
        yield from self.ports[mode].chat(req, cancel)

    def status(self):
        status = self.ports[self.mode].status()
        if self.mode == 'cloud':
            return {**status, 'ready': bool(status.get('key_present'))}
        engine = status.get('engine', {})
        return {**status, 'ready': bool(engine.get('model')), 'model': engine.get('model', '')}

    def unload_all(self):
        return self.ports['local'].unload_all()
