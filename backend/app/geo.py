import math
from shapely.geometry import shape, Polygon, LineString, mapping
from shapely import transform as _transform

def transform(func, geom):
    return _transform(geom, func, interleaved=False)
from shapely.validation import explain_validity
from shapely.errors import GEOSException
from pyproj import CRS, Transformer


def polygon(data):
    try:
        coords=data.get('coordinates',[])
        if sum(len(r) for r in coords)>2000 or len(coords)>30: raise ValueError('Boundary exceeds 2,000 vertices or 30 rings')
        p = shape(data)
        if not isinstance(p, Polygon) or p.is_empty or not p.is_valid:
            raise ValueError('Invalid polygon: ' + explain_validity(p))
        if p.has_z: raise ValueError('Use longitude and latitude only')
        x1,y1,x2,y2 = p.bounds
        if not (-180 <= x1 <= x2 <= 180 and -80 <= y1 <= y2 <= 84):
            raise ValueError('Coordinates must be longitude/latitude within UTM coverage (-80 to 84 latitude)')
        if x2-x1 > .2 or y2-y1 > .2: raise ValueError('Farm extent must be less than 0.2 degrees per axis')
        if p.area == 0: raise ValueError('Boundary must have area')
        return p
    except (TypeError, KeyError, AttributeError, GEOSException) as e: raise ValueError('Expected GeoJSON Polygon') from e


def projection(p):
    c = p.centroid
    zone = min(60, max(1, int((c.x+180)/6)+1))
    crs = CRS.from_epsg((32600 if c.y>=0 else 32700)+zone)
    return Transformer.from_crs(4326, crs, always_xy=True).transform, Transformer.from_crs(crs,4326,always_xy=True).transform


def area(data):
    p=polygon(data); f,_=projection(p)
    a=transform(f,p).area/10000
    if a < .001: raise ValueError('Farm must be at least 10 square metres')
    return a


def generate(data, options):
    p=polygon(data); forward, backward=projection(p); metric=transform(forward,p)
    full_metric=metric
    exclusions=[]
    for raw in options.exclusions:
        e=transform(forward,polygon(raw))
        if not full_metric.covers(e): raise ValueError('Exclusions must be within farm')
        exclusions.append(raw); metric=metric.difference(e)
    if metric.is_empty: raise ValueError('Exclusions remove the whole farm')
    camera=options.sensor_width_mm is not None and options.focal_length_mm is not None
    if camera:
        width=options.altitude_m*options.sensor_width_mm/options.focal_length_mm
        height=width*options.image_height_px/options.image_width_px
    else: width=options.altitude_m*.8; height=width*.75
    spacing=max(1,width*(1-options.side_overlap)); trigger=max(1,height*(1-options.front_overlap))
    minx,miny,maxx,maxy=metric.bounds
    if (maxy-miny)/spacing > 2000: raise ValueError('Too many survey lines; increase altitude or reduce overlap')
    count=max(1,math.ceil((maxy-miny)/spacing)); segments=[]
    for i in range(count):
        y=miny+(i+.5)*(maxy-miny)/count
        cut=metric.intersection(LineString([(minx-1,y),(maxx+1,y)]))
        lines=list(cut.geoms) if hasattr(cut,'geoms') else [cut]
        lines=sorted([l for l in lines if l.geom_type=='LineString' and l.length>.1],key=lambda l:l.bounds[0],reverse=bool(i%2))
        for line in lines:
            coords=list(line.coords)
            if i%2: coords.reverse()
            segments.append(LineString(coords))
    if not segments: raise ValueError('No survey route could be generated')
    if len(segments)>2000: raise ValueError('Too many survey segments')
    transit=[LineString([a.coords[-1],b.coords[0]]) for a,b in zip(segments,segments[1:]) if a.coords[-1]!=b.coords[0]]
    length=sum(s.length for s in segments); transfers=sum(s.length for s in transit)
    points=[]
    for s in segments:
        n=max(1,math.ceil(s.length/trigger))
        for i in range(n+1):
            pt=transform(backward,s.interpolate(i/n,normalized=True))
            points.append([pt.x,pt.y])
    if len(points)>10000: raise ValueError('Plan exceeds 10,000 captures')
    return {'survey_segments':[mapping(transform(backward,s)) for s in segments],
            'transit_segments':[mapping(transform(backward,s)) for s in transit],
            'capture_points':points,'launch':points[0],'return':points[-1],
            'survey_distance_m':round(length,1),'transit_distance_m':round(transfers,1),
            'duration_s':round((length+transfers)/options.speed_mps), 'image_count':len(points),
            'spacing_m':round(spacing,2),'camera_coverage':camera,'provisional':not camera,
            'exclusions':exclusions,'options':options.model_dump(),
            'warning':'Planning estimate only. Transit segments may cross exclusions or leave the boundary. Separately validate terrain, obstacles, airspace, weather, battery and aircraft capability. This is not an approved flight plan.'}
