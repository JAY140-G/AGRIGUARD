import io, json
import pytest
from shapely.geometry import shape, Point
from app.geo import generate, projection, transform
from app.schemas import PlanInput
from app.drone import Simulator, transition
from app.worker import tick_mission, process_job

def test_waypoint_margin_and_direction(boundary):
    # Test margin and direction angle
    plan = generate(boundary, PlanInput(margin_m=10.0, direction_deg=45.0, altitude_m=80.0))
    assert plan['margin_m'] == 10.0
    assert plan['direction_deg'] == 45.0
    assert 'waypoints' in plan
    assert len(plan['waypoints']) > 0
    assert plan['waypoint_count'] == len(plan['waypoints'])

    # Validate ordered waypoints
    f, _ = projection(shape(boundary))
    farm_metric = transform(f, shape(boundary))
    for idx, wp in enumerate(plan['waypoints']):
        assert wp['order'] == idx + 1
        assert wp['alt_m'] == 80.0
        assert -90 <= wp['lat'] <= 90
        assert -180 <= wp['lon'] <= 180
        # Check containment
        pt_metric = transform(f, Point(wp['lon'], wp['lat']))
        assert farm_metric.buffer(1.0).covers(pt_metric)
        assert wp['valid_containment'] is True

    # Validate assumptions
    assert len(plan['assumptions']) >= 4
    assert any('constant' in a for a in plan['assumptions'])
    assert any('Turnaround' in a for a in plan['assumptions'])

def test_excessive_margin_error():
    # Small 50m x 50m field where 35m margin (within 100m validation limit) collapses area
    small_boundary = {
        'type': 'Polygon',
        'coordinates': [[[75.7800, 26.9100], [75.7805, 26.9100], [75.7805, 26.9105], [75.7800, 26.9105], [75.7800, 26.9100]]]
    }
    with pytest.raises(ValueError) as exc:
        generate(small_boundary, PlanInput(margin_m=35.0))
    assert 'leaves no surveyable area' in str(exc.value)

def test_custom_spacing_and_capture_policy(boundary):
    plan = generate(boundary, PlanInput(spacing_m=42.0, capture_policy='distance', capture_interval_m=20.0))
    assert plan['spacing_m'] == 42.0
    assert plan['capture_policy'] == 'distance'
    assert len(plan['waypoints']) > 0

def test_preflight_and_obstacle_and_rtl_workflows(client, farm):
    # Create mission with margin and direction
    res = client.post('/api/farms/' + farm['id'] + '/missions', json={
        'altitude_m': 100,
        'margin_m': 5,
        'direction_deg': 30,
        'speed_mps': 6
    }).json()
    mid = res['id']
    base = '/api/missions/' + mid

    # 1. Preflight check
    pre = client.post(base + '/preflight').json()
    assert pre['state'] == 'ready'
    telem = client.get(base + '/telemetry').json()
    assert telem.get('preflight', {}).get('passed') is True

    # 2. Start from ready state
    started = client.post(base + '/start').json()
    assert started['state'] == 'queued'
    tick_mission()
    assert client.get(base).json()['state'] == 'running'

    # 3. Obstacle awareness and safe-state hold
    obs = client.post(base + '/inject_obstacle').json()
    # Safe-state policy: automatically puts flight in holding / paused
    assert obs['state'] == 'paused'
    telem_obs = client.get(base + '/telemetry').json()
    assert telem_obs['obstacle']['detected'] is True
    assert telem_obs['obstacle']['safe_state_triggered'] is True
    assert telem_obs['obstacle']['reported_response'] == 'hold'
    assert telem_obs['obstacle']['is_simulated'] is True

    # Clear obstacle
    cleared = client.post(base + '/clear_obstacle').json()
    telem_clear = client.get(base + '/telemetry').json()
    assert telem_clear['obstacle']['detected'] is False

    # Resume survey
    client.post(base + '/resume')
    assert client.get(base).json()['state'] == 'running'
    tick_mission()

    # 4. Return to Launch (RTL)
    rtl = client.post(base + '/rtl').json()
    assert rtl['state'] == 'rtl'
    # Tick RTL until return to launch completes
    for _ in range(15):
        tick_mission()
        if client.get(base).json()['state'] == 'completed':
            break
    assert client.get(base).json()['state'] == 'completed'

def test_qgc_and_mavlink_exports(client, farm):
    m = client.post('/api/farms/' + farm['id'] + '/missions', json={'altitude_m': 75}).json()
    mid = m['id']

    # QGroundControl Plan export
    qgc_resp = client.get('/api/missions/' + mid + '/export/qgc-plan')
    assert qgc_resp.status_code == 200
    assert 'agriscan-mission-' in qgc_resp.headers['content-disposition']
    qgc_data = qgc_resp.json()
    assert qgc_data['fileType'] == 'Plan'
    assert qgc_data['groundStation'] == 'QGroundControl'
    assert len(qgc_data['mission']['items']) > 2
    # First item is takeoff (cmd 22), last item is RTL (cmd 20)
    assert qgc_data['mission']['items'][0]['command'] == 22
    assert qgc_data['mission']['items'][-1]['command'] == 20

    # MAVLink Waypoint export
    wpl_resp = client.get('/api/missions/' + mid + '/export/mavlink-wpl')
    assert wpl_resp.status_code == 200
    assert wpl_resp.text.startswith('QGC WPL 110')
    lines = wpl_resp.text.strip().splitlines()
    assert len(lines) > 3

def test_object_detection_contract_and_metadata(client, farm):
    m = client.post('/api/farms/' + farm['id'] + '/missions', json={'altitude_m': 90, 'direction_deg': 15}).json()
    mid = m['id']
    client.post('/api/missions/' + mid + '/start')
    tick_mission()
    while process_job(): pass

    photos = client.get('/api/farms/' + farm['id'] + '/images?mission_id=' + mid).json()
    assert len(photos) >= 1
    p = photos[0]

    # Verify capture metadata
    assert p['metadata']['altitude_m'] == 90
    assert 'heading_deg' in p['metadata']
    assert p['metadata']['capture_policy'] == 'waypoints'
    assert p['metadata']['upload_status'] == 'persisted'
    assert 'geolocation_note' in p['metadata']

    # Verify object detection status
    obj_det = p['result'].get('object_detection', {})
    assert obj_det.get('detector_configured') is False
    assert obj_det.get('status') == 'unavailable'
    assert obj_det.get('detections') == []
    assert 'No object detector configured' in obj_det.get('message', '')

    # Clean up test mission
    client.post('/api/missions/' + mid + '/abort')
