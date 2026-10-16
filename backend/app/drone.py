from typing import Protocol

TRANSITIONS={'draft':{'plan':'planned'},'planned':{'start':'queued','abort':'aborted'},'queued':{'run':'running','abort':'aborted'},'running':{'pause':'paused','complete':'completed','fail':'failed','abort':'aborted'},'paused':{'resume':'running','abort':'aborted','fail':'failed'}}

def transition(state,action):
    target=TRANSITIONS.get(state,{}).get(action)
    if not target: raise ValueError(f'Cannot {action} mission in {state} state')
    return target

class DroneAdapter(Protocol):
    def connect(self): ...
    def disconnect(self): ...
    def capabilities(self) -> dict: ...
    def telemetry(self, mission) -> dict: ...
    def validate(self, plan) -> list[str]: ...
    def upload(self, plan): ...
    def start(self, mission): ...
    def pause(self, mission): ...
    def resume(self, mission): ...
    def abort(self, mission): ...
    def status(self, mission) -> str: ...
    def captured_events(self, mission) -> list[dict]: ...

class Simulator:
    connected=False
    def connect(self): self.connected=True; return self.capabilities()
    def disconnect(self): self.connected=False
    def capabilities(self): return {'adapter':'simulator','live_control':False,'camera':'synthetic aerial image','accelerated':True}
    def telemetry(self,mission):
        import json
        return json.loads(mission.telemetry)
    def validate(self,plan): return [] if plan.get('capture_points') else ['Plan has no capture points']
    def upload(self,plan):
        if not self.connected: raise ValueError('Simulator disconnected')
        errors=self.validate(plan)
        if errors: raise ValueError('; '.join(errors))
        self.plan=plan
    def start(self,m): m.state=transition(m.state,'start')
    def pause(self,m): m.state=transition(m.state,'pause')
    def resume(self,m): m.state=transition(m.state,'resume')
    def abort(self,m): m.state=transition(m.state,'abort')
    def status(self,m): return m.state
    def captured_events(self,m): return self.telemetry(m).get('captured_events',[])
