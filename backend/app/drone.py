from typing import Protocol
import json

TRANSITIONS = {
    'draft': {'plan': 'planned'},
    'planned': {'preflight': 'ready', 'start': 'queued', 'abort': 'aborted'},
    'ready': {'start': 'queued', 'abort': 'aborted'},
    'queued': {'run': 'running', 'abort': 'aborted'},
    'running': {
        'pause': 'paused',
        'hold': 'paused',
        'rtl': 'rtl',
        'complete': 'completed',
        'fail': 'failed',
        'abort': 'aborted',
    },
    'paused': {
        'resume': 'running',
        'rtl': 'rtl',
        'abort': 'aborted',
        'fail': 'failed',
    },
    'rtl': {
        'complete': 'completed',
        'abort': 'aborted',
        'fail': 'failed',
    },
}

def transition(state, action):
    target = TRANSITIONS.get(state, {}).get(action)
    if not target: raise ValueError(f'Cannot {action} mission in {state} state')
    return target

class DroneAdapter(Protocol):
    def connect(self) -> dict: ...
    def disconnect(self): ...
    def capabilities(self) -> dict: ...
    def telemetry(self, mission) -> dict: ...
    def preflight_check(self, mission) -> dict: ...
    def validate(self, plan) -> list[str]: ...
    def upload(self, plan): ...
    def start(self, mission): ...
    def pause(self, mission): ...
    def resume(self, mission): ...
    def rtl(self, mission): ...
    def abort(self, mission): ...
    def status(self, mission) -> str: ...
    def captured_events(self, mission) -> list[dict]: ...

class Simulator:
    """Clearly labelled simulation adapter.
    Emulates high-level flight controller interface with telemetry and obstacle alerts.
    Never arms or operates live physical hardware.
    """
    connected = False
    def connect(self):
        self.connected = True
        return self.capabilities()

    def disconnect(self):
        self.connected = False

    def capabilities(self):
        return {
            'adapter': 'simulation',
            'label': 'Clearly labelled simulation adapter',
            'is_simulation': True,
            'live_control': False,
            'supported_protocols': ['MAVLink (emulated)', 'QGC Plan export'],
            'camera': 'synthetic aerial imagery',
            'accelerated': True,
            'obstacle_sensor': 'simulated',
            'safe_state_policy': 'automatic_hold_on_obstacle'
        }

    def telemetry(self, mission):
        data = json.loads(mission.telemetry or '{}')
        if 'obstacle' not in data:
            data['obstacle'] = {
                'sensor_status': 'simulated_operational',
                'is_simulated': True,
                'detected': False,
                'distance_m': None,
                'bearing_deg': None,
                'safe_state_triggered': False,
                'reported_response': 'none'
            }
        return data

    def preflight_check(self, plan: dict) -> dict:
        points = plan.get('capture_points', [])
        return {
            'passed': len(points) > 0,
            'battery_ok': True,
            'battery_percent': 100.0,
            'gps_lock': True,
            'simulated_satellites': 14,
            'geofence_verified': True,
            'waypoint_count': len(points),
            'camera_ready': True,
            'notes': 'Simulated pre-flight validation complete. Safe to arm simulator.'
        }

    def validate(self, plan):
        errors = []
        if not plan.get('capture_points'):
            errors.append('Plan has no capture points')
        if len(plan.get('capture_points', [])) > 10000:
            errors.append('Capture count exceeds flight controller waypoint capacity (10,000)')
        return errors

    def upload(self, plan):
        if not self.connected: raise ValueError('Simulator disconnected')
        errors = self.validate(plan)
        if errors: raise ValueError('; '.join(errors))
        self.plan = plan

    def start(self, m): m.state = transition(m.state, 'start')
    def pause(self, m): m.state = transition(m.state, 'pause')
    def resume(self, m): m.state = transition(m.state, 'resume')
    def rtl(self, m): m.state = transition(m.state, 'rtl')
    def abort(self, m): m.state = transition(m.state, 'abort')
    def status(self, m): return m.state
    def captured_events(self, m): return self.telemetry(m).get('captured_events', [])

