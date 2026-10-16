import {useEffect, useRef, useState, useCallback} from 'react';
import * as maplibregl from 'maplibre-gl';
import {Map as GLMap, Marker, GeoJSONSource} from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
maplibregl.setWorkerUrl(workerUrl);
import {Crosshair, Layers, Minus, Plus, Search, AlertTriangle, Loader, Satellite, X, MapPin, Undo2, Trash2, Check} from 'lucide-react';
import type {Farm, Mission, Photo, Position, Polygon} from './types';
import {featureCollection} from './types';

/* ─── Types ────────────────────────────────────────────────────────────────── */
export type BasemapMode = 'maptiler-satellite' | 'maptiler-hybrid' | 'maptiler-streets' | 'offline';

export interface GeocodeResult {
  id: string;
  text: string;
  place_name: string;
  center: Position;
  bbox?: [number, number, number, number];
}

/* ─── Blank fallback style (offline canvas) ─────────────────────────────────── */
const blankStyle: maplibregl.StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{id: 'background', type: 'background', paint: {'background-color': '#e5e9db'}}]
};

/* ─── Compute polygon area in hectares via spherical formula ──────────────── */
export function computeAreaHa(coords: Position[]): number {
  if (coords.length < 3) return 0;
  const R = 6378137; // WGS84 earth radius in meters
  let total = 0;
  const n = coords.length;
  for (let i = 0; i < n; i++) {
    const [lon1, lat1] = coords[i];
    const [lon2, lat2] = coords[(i + 1) % n];
    const radLat1 = (lat1 * Math.PI) / 180;
    const radLat2 = (lat2 * Math.PI) / 180;
    const dLon = ((lon2 - lon1) * Math.PI) / 180;
    total += dLon * (2 + Math.sin(radLat1) + Math.sin(radLat2));
  }
  const areaM2 = Math.abs((total * R * R) / 2);
  return areaM2 / 10000;
}

/* ─── Resolve MapTiler style URL for a given mode ─────────────────────────── */
function getStyleUrl(mode: BasemapMode, key: string): string | maplibregl.StyleSpecification {
  if (mode === 'offline') return blankStyle;
  if (!key) {
    if (mode === 'maptiler-streets') return 'https://tiles.openfreemap.org/styles/liberty';
    return blankStyle;
  }
  switch (mode) {
    case 'maptiler-satellite':
      return `https://api.maptiler.com/maps/satellite/style.json?key=${key}`;
    case 'maptiler-hybrid':
      return `https://api.maptiler.com/maps/hybrid/style.json?key=${key}`;
    case 'maptiler-streets':
      return `https://api.maptiler.com/maps/streets-v2/style.json?key=${key}`;
    default:
      return blankStyle;
  }
}

/* ─── Resolve the persisted basemap preference ──────────────────────────────── */
function resolveInitialMode(): BasemapMode {
  const stored = localStorage.getItem('agriscan-basemap-mode');
  const key = import.meta.env.VITE_MAPTILER_API_KEY?.trim() || '';

  if (stored) {
    if (stored === 'maptiler-satellite' || stored === 'google-satellite' || stored === 'satellite') {
      return key ? 'maptiler-satellite' : 'maptiler-streets';
    }
    if (stored === 'maptiler-hybrid' || stored === 'google-hybrid' || stored === 'hybrid') {
      return key ? 'maptiler-hybrid' : 'maptiler-streets';
    }
    if (stored === 'maptiler-streets' || stored === 'osm' || stored === 'streets') {
      return 'maptiler-streets';
    }
    if (stored === 'offline') return 'offline';
  }

  const legacy = localStorage.getItem('agriscan-map-style');
  if (legacy === 'offline') return 'offline';

  return key ? 'maptiler-satellite' : 'maptiler-streets';
}

/* ─── Component ─────────────────────────────────────────────────────────────── */
export function FieldMap({
  farm, mission, photos, selected, onSelect,
  drawMode, onBoundary, onCancelDraw, draft, exclusions, onError
}: {
  farm?: Farm;
  mission?: Mission;
  photos: Photo[];
  selected?: string;
  onSelect: (p: Photo) => void;
  drawMode: 'boundary' | 'exclusion' | null;
  onBoundary: (p: Polygon) => void;
  onCancelDraw?: () => void;
  draft?: Polygon;
  exclusions: Polygon[];
  onError: (s: string) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const searchWrapRef = useRef<HTMLDivElement>(null);
  const map = useRef<GLMap | null>(null);
  const markers = useRef<Marker[]>([]);
  const draftCornerMarkers = useRef<Marker[]>([]);
  const points = useRef<Position[]>([]);

  const [ready, setReady] = useState(false);
  const [mapMode, setMapMode] = useState<BasemapMode>(resolveInitialMode);
  const [basemapStatus, setBasemapStatus] = useState<'idle' | 'loading' | 'ok' | 'error'>('idle');
  const [basemapError, setBasemapError] = useState('');
  const [vertexCount, setVertexCount] = useState(0);
  const [liveAreaHa, setLiveAreaHa] = useState(0);

  // Search and geocoding state
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState<GeocodeResult[]>([]);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [searching, setSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const [selectedPlace, setSelectedPlace] = useState<{ name: string; center: Position } | null>(null);
  const searchDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isSelectingRef = useRef(false);

  const modeRef = useRef(drawMode);
  const boundaryCallback = useRef(onBoundary);
  const cancelCallback = useRef(onCancelDraw);
  modeRef.current = drawMode;
  boundaryCallback.current = onBoundary;
  cancelCallback.current = onCancelDraw;

  const maptilerKey = import.meta.env.VITE_MAPTILER_API_KEY?.trim() || '';

  /* ─ Close search dropdown when clicking outside ─────────────────────────── */
  useEffect(() => {
    function handleClickOutside(e: MouseEvent | TouchEvent) {
      if (searchWrapRef.current && !searchWrapRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
        setActiveIndex(-1);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('touchstart', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('touchstart', handleClickOutside);
    };
  }, []);

  /* ─ Tune raster satellite layer for optimal clarity ──────────────────────── */
  function tuneSatelliteClarity(m: GLMap) {
    if (m.getLayer('Satellite')) {
      try {
        // Remove cross-fade duration lag to show crisp tiles immediately
        m.setPaintProperty('Satellite', 'raster-fade-duration', 0);
        m.setPaintProperty('Satellite', 'raster-resampling', 'linear');
      } catch {
        // Ignore if layer does not support property
      }
    }
  }

  /* ─ Add all AgriScan overlay sources and layers ─────────────────────────── */
  function addOverlayLayers(m: GLMap) {
    for (const name of ['farm', 'route', 'transit', 'photos', 'draft', 'exclusions', 'drone', 'waypoints']) {
      if (!m.getSource(name)) m.addSource(name, {type: 'geojson', data: featureCollection([])});
    }
    const addLayer = (spec: maplibregl.LayerSpecification) => {
      if (!m.getLayer(spec.id)) m.addLayer(spec);
    };

    addLayer({id: 'farm-fill',       type: 'fill',   source: 'farm',       paint: {'fill-color': '#3a8745', 'fill-opacity': 0.16}});
    addLayer({id: 'farm-line',       type: 'line',   source: 'farm',       paint: {'line-color': '#2f703e', 'line-width': 2.5}});
    addLayer({id: 'exclusion-fill',  type: 'fill',   source: 'exclusions', paint: {'fill-color': '#bc6c39', 'fill-opacity': 0.3}});
    addLayer({id: 'route-line',      type: 'line',   source: 'route',      paint: {'line-color': '#e1a738', 'line-width': 2.3}});
    addLayer({id: 'transit-line',    type: 'line',   source: 'transit',    paint: {'line-color': '#ac673c', 'line-width': 2, 'line-dasharray': [2, 2]}});
    addLayer({id: 'waypoints-point', type: 'circle', source: 'waypoints',  paint: {'circle-radius': 3.5, 'circle-color': '#f59e0b', 'circle-stroke-color': '#78350f', 'circle-stroke-width': 1}});

    // Live draft preview polygon fill & boundary line
    addLayer({
      id: 'draft-fill',
      type: 'fill',
      source: 'draft',
      filter: ['==', ['geometry-type'], 'Polygon'],
      paint: {'fill-color': '#22c55e', 'fill-opacity': 0.22}
    });
    addLayer({
      id: 'draft-line',
      type: 'line',
      source: 'draft',
      filter: ['==', ['geometry-type'], 'LineString'],
      paint: {'line-color': '#236644', 'line-width': 3, 'line-dasharray': [2, 1]}
    });
    addLayer({
      id: 'draft-vertices',
      type: 'circle',
      source: 'draft',
      filter: ['==', ['geometry-type'], 'Point'],
      paint: {'circle-radius': 6, 'circle-color': '#ffffff', 'circle-stroke-color': '#236644', 'circle-stroke-width': 2}
    });

    addLayer({id: 'drone-point',     type: 'circle', source: 'drone',      paint: {'circle-radius': 9, 'circle-color': '#225bdf', 'circle-stroke-color': 'white', 'circle-stroke-width': 3}});
    tuneSatelliteClarity(m);
  }

  /* ─ Live drawing updates ─────────────────────────────────────────────────── */
  function updateDrawing() {
    const m = map.current; if (!m) return;
    const p = points.current;
    const fs: GeoJSON.Feature[] = [];

    // Clear existing draft corner markers
    draftCornerMarkers.current.forEach(mk => mk.remove());
    draftCornerMarkers.current = [];

    if (p.length >= 3) {
      // Show closed polygon preview fill
      fs.push({type: 'Feature', geometry: {type: 'Polygon', coordinates: [[...p, p[0]]]}, properties: {}});
      // Show closed boundary line
      fs.push({type: 'Feature', geometry: {type: 'LineString', coordinates: [...p, p[0]]}, properties: {}});
      setLiveAreaHa(computeAreaHa(p));
    } else if (p.length >= 2) {
      fs.push({type: 'Feature', geometry: {type: 'LineString', coordinates: p}, properties: {}});
      setLiveAreaHa(0);
    } else {
      setLiveAreaHa(0);
    }

    p.forEach((c, idx) => {
      fs.push({type: 'Feature', geometry: {type: 'Point', coordinates: c}, properties: {}});
      // Create numbered corner marker during drawing
      const el = document.createElement('div');
      el.className = 'corner-marker drafting';
      el.textContent = String(idx + 1);
      el.title = `Corner #${idx + 1}: ${c[1].toFixed(5)}, ${c[0].toFixed(5)}`;
      const marker = new Marker({element: el}).setLngLat(c).addTo(m);
      draftCornerMarkers.current.push(marker);
    });

    (m.getSource('draft') as GeoJSONSource)?.setData(featureCollection(fs));
    setVertexCount(p.length);
  }

  function finish() {
    const p = points.current;
    if (p.length < 3) {
      onError('A valid boundary requires at least 3 distinct corner points.');
      return;
    }
    const calculatedArea = computeAreaHa(p);
    if (calculatedArea <= 0.0001) {
      onError('Invalid boundary geometry. Points must enclose an actual field area.');
      return;
    }

    const closedPolygon: Polygon = {type: 'Polygon', coordinates: [[...p, p[0]]]};
    points.current = [];
    draftCornerMarkers.current.forEach(mk => mk.remove());
    draftCornerMarkers.current = [];
    updateDrawing();
    boundaryCallback.current(closedPolygon);
  }

  function cancelDrawing() {
    points.current = [];
    draftCornerMarkers.current.forEach(mk => mk.remove());
    draftCornerMarkers.current = [];
    updateDrawing();
    if (cancelCallback.current) {
      cancelCallback.current();
    }
  }

  /* ─ Switch basemap while preserving overlays ──────────────────────────────── */
  const switchBasemap = useCallback(async (mode: BasemapMode) => {
    const m = map.current;
    if (!m) return;
    setMapMode(mode);
    localStorage.setItem('agriscan-basemap-mode', mode);
    localStorage.removeItem('agriscan-map-style');

    if (mode.startsWith('maptiler') && !maptilerKey) {
      if (mode === 'maptiler-streets') {
        m.setStyle('https://tiles.openfreemap.org/styles/liberty');
        m.once('style.load', () => addOverlayLayers(m));
        return;
      }
      setBasemapError('VITE_MAPTILER_API_KEY is not configured. Add your key to frontend/.env.local for hosted satellite imagery.');
      setBasemapStatus('error');
      setMapMode('maptiler-streets');
      m.setStyle('https://tiles.openfreemap.org/styles/liberty');
      m.once('style.load', () => addOverlayLayers(m));
      return;
    }

    setBasemapStatus('loading');
    setBasemapError('');

    try {
      const styleSpec = getStyleUrl(mode, maptilerKey);
      m.setStyle(styleSpec);
      m.once('style.load', () => {
        addOverlayLayers(m);
        setBasemapStatus('ok');
      });
    } catch (err) {
      const msg = (err as Error).message;
      setBasemapError(msg);
      setBasemapStatus('error');
      onError(`Map error: ${msg}`);
      m.setStyle(blankStyle);
      m.once('style.load', () => addOverlayLayers(m));
    }
  }, [maptilerKey, onError]);

  /* ─ Initial map construction ─────────────────────────────────────────────── */
  useEffect(() => {
    if (!container.current) return;
    const initialMode = resolveInitialMode();
    const style = getStyleUrl(initialMode, maptilerKey);

    const m = new maplibregl.Map({
      container: container.current,
      style: style,
      center: [75.782, 26.9115], // Default focus on agricultural area
      zoom: 15,
      minZoom: 1,
      maxZoom: 20, // Prevents digital overzooming beyond native optical satellite resolution
      pitch: 0,
      maxPitch: 60,
      dragRotate: false, // Maintain crisp 2D overhead surveying perspective
      attributionControl: {compact: true},
      maxTileCacheSize: 200, // Keep loaded tiles in memory for responsive panning
    });
    map.current = m;

    m.on('idle', () => {
      if (!container.current || !m.getLayer('farm-fill')) return;
      container.current.dataset.boundaryFeatures = String(m.queryRenderedFeatures({layers: ['farm-fill']}).length);
      container.current.dataset.routeFeatures    = String(m.queryRenderedFeatures({layers: ['route-line']}).length);
    });

    m.on('load', () => {
      addOverlayLayers(m);
      setReady(true);
      setBasemapStatus('ok');
    });

    m.on('error', (e) => {
      if (e.error && !e.error.message.includes('Image')) {
        setBasemapError(e.error.message);
        setBasemapStatus('error');
      }
    });

    m.on('click', e => {
      if (modeRef.current) {
        points.current.push([e.lngLat.lng, e.lngLat.lat]);
        updateDrawing();
      }
    });
    m.doubleClickZoom.disable();

    return () => {
      m.remove();
      map.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ─ Sync draw mode cursor ─────────────────────────────────────────────────── */
  useEffect(() => {
    points.current = [];
    draftCornerMarkers.current.forEach(mk => mk.remove());
    draftCornerMarkers.current = [];
    if (ready) updateDrawing();
    if (map.current) map.current.getCanvas().style.cursor = drawMode ? 'crosshair' : '';
  }, [drawMode, ready]);

  /* ─ Sync overlays (farm polygon, route, waypoints, photo markers) ────────── */
  useEffect(() => {
    const m = map.current; if (!ready || !m) return;
    const set = (name: string, fs: GeoJSON.Feature[]) => (m.getSource(name) as GeoJSONSource)?.setData(featureCollection(fs));

    set('farm',       (draft || farm?.boundary) ? [{type: 'Feature', geometry: (draft || farm!.boundary), properties: {}}] : []);
    set('route',      (mission?.plan.survey_segments  || []).map(geometry => ({type: 'Feature', geometry, properties: {}})));
    set('transit',    (mission?.plan.transit_segments || []).map(geometry => ({type: 'Feature', geometry, properties: {}})));
    set('waypoints',  (mission?.plan.capture_points   || []).map(coords   => ({type: 'Feature', geometry: {type: 'Point', coordinates: coords}, properties: {}})));
    set('exclusions', exclusions.map(geometry => ({type: 'Feature', geometry, properties: {}})));
    set('drone',      mission?.telemetry.position ? [{type: 'Feature', geometry: {type: 'Point', coordinates: mission.telemetry.position}, properties: {}}] : []);

    markers.current.forEach(mk => mk.remove());
    markers.current = [];

    // Photo markers
    for (const p of photos) {
      if (p.lon === null || p.lat === null) continue;
      const el = document.createElement('button');
      el.type = 'button';
      el.className = 'photo-marker ' + (p.result?.label.startsWith('Suspected') ? 'alert-marker' : '') + (selected === p.id ? ' selected' : '');
      el.title = p.result?.label || p.status;
      el.setAttribute('aria-label', `Open image ${p.id}`);
      el.onclick = e => { e.stopPropagation(); onSelect(p); };
      markers.current.push(new Marker({element: el}).setLngLat([p.lon, p.lat]).addTo(m));
    }

    // Launch & Return endpoint markers
    if (mission && !drawMode) {
      for (const [pt, label] of [[mission.plan.launch, 'L'], [mission.plan.return, 'R']] as [Position, string][]) {
        const el = document.createElement('div'); el.className = 'route-endpoint'; el.textContent = label;
        el.title = label === 'L' ? 'Launch point' : 'Return point';
        markers.current.push(new Marker({element: el}).setLngLat(pt).addTo(m));
      }
    }

    // Numbered, draggable corner markers on saved/draft boundary when not drawing
    if (draft && !drawMode) {
      draft.coordinates[0].slice(0, -1).forEach((pt, i) => {
        const el = document.createElement('div');
        el.className = 'corner-marker';
        el.textContent = String(i + 1);
        el.title = `Corner #${i + 1}: ${pt[1].toFixed(5)}, ${pt[0].toFixed(5)} (Drag to adjust)`;

        const v = new Marker({element: el, draggable: true}).setLngLat(pt).addTo(m);
        v.on('dragend', () => {
          const c = draft.coordinates[0].slice(0, -1).map(p => [...p] as Position);
          const pos = v.getLngLat();
          c[i] = [pos.lng, pos.lat];
          boundaryCallback.current({type: 'Polygon', coordinates: [[...c, c[0]]]});
        });
        markers.current.push(v);
      });
    }
  }, [ready, farm, draft, mission, photos, selected, exclusions, drawMode]);

  /* ─ Auto-center on selected photo ───────────────────────────────────────── */
  useEffect(() => {
    if (!ready || !map.current || !selected) return;
    const p = photos.find(x => x.id === selected);
    if (p && p.lon !== null && p.lat !== null) {
      map.current.flyTo({center: [p.lon, p.lat], zoom: 17, duration: 700});
    }
  }, [selected, ready, photos]);

  /* ─ Fit farm boundary on farm selection ──────────────────────────────────── */
  useEffect(() => {
    if (!ready || !farm || !map.current) return;
    const b = new maplibregl.LngLatBounds();
    farm.boundary.coordinates[0].forEach(p => b.extend(p));
    // Zoom 18 ensures crisp optical resolution without blur
    map.current.fitBounds(b, {padding: 70, maxZoom: 18, duration: 700});
  }, [farm?.id, ready]);

  /* ─ Debounced Geocoding Search ───────────────────────────────────────────── */
  useEffect(() => {
    // If the change came from user selecting a suggestion, don't reopen dropdown!
    if (isSelectingRef.current) {
      isSelectingRef.current = false;
      return;
    }

    const trimmed = query.trim();
    if (!trimmed || trimmed.length < 2) {
      setSuggestions([]);
      setShowDropdown(false);
      setActiveIndex(-1);
      return;
    }

    // Coordinate shortcut: "lat, lon"
    const coordMatch = trimmed.match(/^([-+]?\d{1,2}(?:\.\d+)?)[,\s]+([-+]?\d{1,3}(?:\.\d+)?)$/);
    if (coordMatch) {
      const lat = parseFloat(coordMatch[1]);
      const lon = parseFloat(coordMatch[2]);
      if (Math.abs(lat) <= 90 && Math.abs(lon) <= 180) {
        setSuggestions([{
          id: 'coord-jump',
          text: `${lat.toFixed(5)}, ${lon.toFixed(5)}`,
          place_name: `Coordinates: ${lat.toFixed(5)}°N, ${lon.toFixed(5)}°E`,
          center: [lon, lat]
        }]);
        setShowDropdown(true);
        setActiveIndex(0);
        return;
      }
    }

    if (searchDebounce.current) clearTimeout(searchDebounce.current);
    searchDebounce.current = setTimeout(async () => {
      setSearching(true);
      try {
        let results: GeocodeResult[] = [];
        if (maptilerKey) {
          const res = await fetch(`https://api.maptiler.com/geocoding/${encodeURIComponent(trimmed)}.json?key=${maptilerKey}&language=en&limit=5`);
          if (res.ok) {
            const data = await res.json();
            results = (data.features || []).map((f: any) => ({
              id: f.id,
              text: f.text || f.place_name,
              place_name: f.place_name,
              center: f.center as Position,
              bbox: f.bbox as [number, number, number, number] | undefined
            }));
          }
        } else {
          // OpenStreetMap Nominatim fallback
          const url = new URL('https://nominatim.openstreetmap.org/search');
          url.searchParams.set('q', trimmed);
          url.searchParams.set('format', 'json');
          url.searchParams.set('limit', '5');
          const res = await fetch(url);
          if (res.ok) {
            const data = await res.json();
            results = data.map((item: any) => ({
              id: String(item.place_id),
              text: item.display_name.split(',')[0],
              place_name: item.display_name,
              center: [parseFloat(item.lon), parseFloat(item.lat)] as Position
            }));
          }
        }
        setSuggestions(results);
        setShowDropdown(results.length > 0);
        setActiveIndex(-1);
      } catch {
        setSuggestions([]);
        setShowDropdown(false);
      } finally {
        setSearching(false);
      }
    }, 300);

    return () => {
      if (searchDebounce.current) clearTimeout(searchDebounce.current);
    };
  }, [query, maptilerKey]);

  function handleSelectResult(result: GeocodeResult) {
    // Flag selection so the query update doesn't trigger a new search and reopen dropdown
    isSelectingRef.current = true;
    setShowDropdown(false);
    setSuggestions([]);
    setActiveIndex(-1);

    setSelectedPlace({name: result.place_name, center: result.center});
    setQuery(result.text || result.place_name);

    if (result.bbox && map.current) {
      map.current.fitBounds(result.bbox, {padding: 60, maxZoom: 18, duration: 800});
    } else if (map.current) {
      map.current.flyTo({center: result.center, zoom: 16, duration: 800});
    }
    // Crucially: Never alters or saves the user's field boundary
  }

  function clearSelectedPlace() {
    isSelectingRef.current = false;
    setSelectedPlace(null);
    setQuery('');
    setSuggestions([]);
    setShowDropdown(false);
    setActiveIndex(-1);
  }

  /* ─ Basemap toggle cycling ───────────────────────────────────────────────── */
  function cycleBasemap() {
    const order: BasemapMode[] = maptilerKey
      ? ['maptiler-satellite', 'maptiler-hybrid', 'maptiler-streets', 'offline']
      : ['maptiler-streets', 'offline'];
    const next = order[(order.indexOf(mapMode) + 1) % order.length];
    void switchBasemap(next);
  }

  const modeLabel: Record<BasemapMode, string> = {
    'maptiler-satellite': '🛰 Satellite',
    'maptiler-hybrid':    '🛰 Hybrid',
    'maptiler-streets':   '🗺 Street',
    'offline':            '✏ Canvas',
  };

  const draftAreaHa = draft ? computeAreaHa(draft.coordinates[0].slice(0, -1)) : 0;

  return (
    <div className="map-shell">
      <div ref={container} className="map-canvas"/>

      {/* Address & Place Search with suggestions */}
      <div ref={searchWrapRef} className="map-search-wrap">
        <form className="map-search" onSubmit={e => {
          e.preventDefault();
          if (activeIndex >= 0 && activeIndex < suggestions.length) {
            handleSelectResult(suggestions[activeIndex]);
          } else if (suggestions.length > 0) {
            handleSelectResult(suggestions[0]);
          }
        }}>
          <Search size={16}/>
          <input
            aria-label="Search address or location"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onFocus={() => { if (suggestions.length > 0) setShowDropdown(true); }}
            onKeyDown={e => {
              if (e.key === 'ArrowDown') {
                e.preventDefault();
                if (!showDropdown && suggestions.length > 0) {
                  setShowDropdown(true);
                  setActiveIndex(0);
                } else if (suggestions.length > 0) {
                  setActiveIndex(i => (i + 1) % suggestions.length);
                }
              } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                if (suggestions.length > 0) {
                  setActiveIndex(i => (i <= 0 ? suggestions.length - 1 : i - 1));
                }
              } else if (e.key === 'Escape') {
                e.preventDefault();
                setShowDropdown(false);
                setActiveIndex(-1);
              }
            }}
            placeholder="Search address, village, city, or lat, lon"
          />
          {query && (
            <button type="button" aria-label="Clear search" onClick={clearSelectedPlace} style={{padding: '0 4px', background: 'transparent', border: 'none'}}>
              <X size={14}/>
            </button>
          )}
          {searching && <Loader size={13} style={{animation: 'spin 1s linear infinite'}}/>}
        </form>

        {/* Suggestion Dropdown */}
        {showDropdown && (
          <div className="search-dropdown">
            {suggestions.length > 0 ? (
              suggestions.map((s, idx) => (
                <button
                  key={s.id}
                  type="button"
                  className={'search-item ' + (idx === activeIndex ? 'active' : '')}
                  onClick={() => handleSelectResult(s)}
                  onMouseEnter={() => setActiveIndex(idx)}
                >
                  <span className="search-item-title">{s.text}</span>
                  <span className="search-item-sub">{s.place_name}</span>
                  <span className="search-item-coords">GPS: {s.center[1].toFixed(5)}, {s.center[0].toFixed(5)}</span>
                </button>
              ))
            ) : (
              !searching && query.trim().length >= 2 && (
                <div style={{padding: '10px 12px', fontSize: '11px', color: '#6b7c68'}}>
                  No places found matching "{query}"
                </div>
              )
            )}
          </div>
        )}

        {/* Active Place Tag */}
        {selectedPlace && (
          <div className="search-pill">
            <MapPin size={12}/>
            <span>{selectedPlace.name.split(',')[0]} ({selectedPlace.center[1].toFixed(4)}, {selectedPlace.center[0].toFixed(4)})</span>
            <button type="button" onClick={clearSelectedPlace} title="Clear location selection"><X size={12}/></button>
          </div>
        )}
      </div>

      {/* Basemap mode label */}
      <div className="map-top-label"><span className="live-dot"/> FIELD WORKSPACE</div>

      {/* Map controls */}
      <div className="map-controls">
        <button aria-label="Zoom in"  onClick={() => map.current?.zoomIn()}><Plus size={18}/></button>
        <button aria-label="Zoom out" onClick={() => map.current?.zoomOut()}><Minus size={18}/></button>
        <button aria-label="Fit farm" onClick={() => {
          if (farm) {
            const b = new maplibregl.LngLatBounds();
            farm.boundary.coordinates[0].forEach(p => b.extend(p));
            map.current?.fitBounds(b, {padding: 70, maxZoom: 18});
          }
        }}><Crosshair size={18}/></button>
        <button aria-label={`Switch basemap (current: ${modeLabel[mapMode]})`} title={modeLabel[mapMode]} onClick={cycleBasemap}>
          {mapMode.includes('satellite') ? <Satellite size={18}/> : <Layers size={18}/>}
        </button>
      </div>

      {/* Basemap mode badge */}
      <div className="basemap-badge" title="Click the layers button to switch basemap">
        {modeLabel[mapMode]}
        {basemapStatus === 'loading' && <Loader size={11} style={{animation: 'spin 1s linear infinite', marginLeft: 4}}/>}
      </div>

      {/* Compact User-friendly Drawing Prompt & Controls */}
      {drawMode && (
        <div className="draw-prompt" role="dialog" aria-label="Boundary drawing tools">
          <b>{drawMode === 'boundary' ? 'Draw field boundary' : 'Draw exclusion zone'}</b>
          <span>Click corners on map in sequence · {vertexCount} corners placed</span>
          {vertexCount >= 3 && (
            <div className="draw-area-badge">
              Calculated Area: {liveAreaHa.toFixed(2)} ha ({(liveAreaHa * 2.47105).toFixed(2)} acres)
            </div>
          )}
          <div className="map-actions-row">
            <button className="secondary" disabled={vertexCount === 0} onClick={() => { points.current.pop(); updateDrawing(); }}>
              <Undo2 size={13}/> Undo point
            </button>
            <button className="secondary" disabled={vertexCount === 0} onClick={() => { points.current = []; updateDrawing(); }}>
              <Trash2 size={13}/> Clear
            </button>
            <button className="secondary" onClick={cancelDrawing}>Cancel</button>
            <button className="primary" disabled={vertexCount < 3} onClick={finish}>
              <Check size={14}/> Save boundary
            </button>
          </div>
        </div>
      )}

      {/* Draggable Corner Area Badge when viewing / editing draft boundary */}
      {!drawMode && draft && draftAreaHa > 0 && (
        <div className="draw-area-badge" style={{position: 'absolute', bottom: '60px', left: '18px', zIndex: 10, background: '#ffffffee', boxShadow: '0 2px 8px #00000015'}}>
          🌾 Field Area: {draftAreaHa.toFixed(2)} ha ({(draftAreaHa * 2.47105).toFixed(2)} acres) · Drag corner numbers to adjust
        </div>
      )}

      {/* Map Notice / Error Banner */}
      {basemapStatus === 'error' && (
        <div className="map-notice map-notice-error">
          <AlertTriangle size={14}/>
          <span><b>Map imagery notice:</b> {basemapError}</span>
          <button onClick={() => { setBasemapStatus('idle'); setBasemapError(''); void switchBasemap(mapMode); }}>Retry</button>
        </div>
      )}

      {/* Missing Key Info Notice */}
      {!maptilerKey && mapMode !== 'offline' && (
        <div className="map-notice">
          MapTiler API key not configured. Using Street basemap.
          Add <code>VITE_MAPTILER_API_KEY</code> to <code>frontend/.env.local</code> for hosted high-resolution satellite imagery.
        </div>
      )}

      {/* Legend */}
      <div className="map-legend">
        <span><i className="legend-boundary"/>Farm boundary</span>
        <span><i className="legend-route"/>Survey line</span>
        <span><i className="legend-alert"/>Suspected finding</span>
      </div>
    </div>
  );
}
