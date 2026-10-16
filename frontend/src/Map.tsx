import {useEffect,useRef,useState} from 'react';
import * as maplibregl from 'maplibre-gl';
import {Map as GLMap,Marker,GeoJSONSource} from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
maplibregl.setWorkerUrl(workerUrl);
import {Crosshair,Layers,Minus,Plus,Search} from 'lucide-react';
import type {Farm,Mission,Photo,Position,Polygon} from './types';
import {featureCollection} from './types';

const blankStyle:maplibregl.StyleSpecification={version:8,sources:{},layers:[{id:'background',type:'background',paint:{'background-color':'#e5e9db'}}]};
export function FieldMap({farm,mission,photos,selected,onSelect,drawMode,onBoundary,draft,exclusions,onError}:{farm?:Farm;mission?:Mission;photos:Photo[];selected?:string;onSelect:(p:Photo)=>void;drawMode:'boundary'|'exclusion'|null;onBoundary:(p:Polygon)=>void;draft?:Polygon;exclusions:Polygon[];onError:(s:string)=>void}){
 const container=useRef<HTMLDivElement>(null),map=useRef<GLMap|null>(null),markers=useRef<Marker[]>([]),points=useRef<Position[]>([]);
 const [ready,setReady]=useState(false),[query,setQuery]=useState(''),[searching,setSearching]=useState(false),[offline,setOffline]=useState(false);
 const modeRef=useRef(drawMode),boundaryCallback=useRef(onBoundary);modeRef.current=drawMode;boundaryCallback.current=onBoundary;
 const [vertexCount,setVertexCount]=useState(0);
 const lastSearch=useRef(0);
 function updateDrawing(){
  const m=map.current;if(!m)return;const p=points.current;
  const fs:GeoJSON.Feature[]=[];
  if(p.length>=2)fs.push({type:'Feature',geometry:{type:'LineString',coordinates:p},properties:{}});
  p.forEach(c=>fs.push({type:'Feature',geometry:{type:'Point',coordinates:c},properties:{}}));
  (m.getSource('draft') as GeoJSONSource)?.setData(featureCollection(fs));setVertexCount(p.length);
 }
 function finish(){if(points.current.length<3){onError('Add at least three boundary points.');return;} const p=points.current;boundaryCallback.current({type:'Polygon',coordinates:[[...p,p[0]]]});points.current=[];updateDrawing();}
 const finishRef=useRef(finish);finishRef.current=finish;
 useEffect(()=>{
  if(!container.current)return;
  const style=localStorage.getItem('agriscan-map-style')||import.meta.env.VITE_MAP_STYLE||'https://tiles.openfreemap.org/styles/liberty';
  const m=new maplibregl.Map({container:container.current,style:style==='offline'?blankStyle:style,center:[75.782,26.9115],zoom:15,pitch:0,attributionControl:{compact:true}});
  map.current=m;
  m.on('error',e=>{console.warn('Map error:',e.error.message);setOffline(true)});
  m.on('idle',()=>{
   if(!container.current||!m.getLayer('farm-fill'))return;
   container.current.dataset.boundaryFeatures=String(m.queryRenderedFeatures({layers:['farm-fill']}).length);
   container.current.dataset.routeFeatures=String(m.queryRenderedFeatures({layers:['route-line']}).length);
  });
  m.on('load',()=>{
   for(const name of ['farm','route','transit','photos','draft','exclusions','drone'])m.addSource(name,{type:'geojson',data:featureCollection([])});
   m.addLayer({id:'farm-fill',type:'fill',source:'farm',paint:{'fill-color':'#3a8745','fill-opacity':.16}});
   m.addLayer({id:'farm-line',type:'line',source:'farm',paint:{'line-color':'#2f703e','line-width':2.5}});
   m.addLayer({id:'exclusion-fill',type:'fill',source:'exclusions',paint:{'fill-color':'#bc6c39','fill-opacity':.3}});
   m.addLayer({id:'route-line',type:'line',source:'route',paint:{'line-color':'#e1a738','line-width':2.3}});
   m.addLayer({id:'transit-line',type:'line',source:'transit',paint:{'line-color':'#ac673c','line-width':2,'line-dasharray':[2,2]}});
   m.addLayer({id:'draft-line',type:'line',source:'draft',filter:['==',['geometry-type'],'LineString'],paint:{'line-color':'#236644','line-width':3,'line-dasharray':[2,1]}});
   m.addLayer({id:'draft-vertices',type:'circle',source:'draft',filter:['==',['geometry-type'],'Point'],paint:{'circle-radius':5,'circle-color':'#fff','circle-stroke-color':'#236644','circle-stroke-width':2}});
   m.addLayer({id:'drone-point',type:'circle',source:'drone',paint:{'circle-radius':9,'circle-color':'#225bdf','circle-stroke-color':'white','circle-stroke-width':3}});
   setReady(true);
  });
  m.on('click',e=>{if(modeRef.current){points.current.push([e.lngLat.lng,e.lngLat.lat]);updateDrawing();}});
  m.doubleClickZoom.disable();
  return()=>{m.remove();map.current=null};
 },[]);
 useEffect(()=>{points.current=[];if(ready)updateDrawing();if(map.current)map.current.getCanvas().style.cursor=drawMode?'crosshair':'';},[drawMode,ready]);
 useEffect(()=>{
  const m=map.current;if(!ready||!m)return;
  const set=(name:string,fs:GeoJSON.Feature[])=>(m.getSource(name) as GeoJSONSource).setData(featureCollection(fs));
  set('farm',(draft||farm?.boundary)?[{type:'Feature',geometry:(draft||farm!.boundary),properties:{}}]:[]);
  set('route',(mission?.plan.survey_segments||[]).map(geometry=>({type:'Feature',geometry,properties:{}})));
  set('transit',(mission?.plan.transit_segments||[]).map(geometry=>({type:'Feature',geometry,properties:{}})));
  set('exclusions',exclusions.map(geometry=>({type:'Feature',geometry,properties:{}})));
  set('drone',mission?.telemetry.position?[{type:'Feature',geometry:{type:'Point',coordinates:mission.telemetry.position},properties:{}}]:[]);
  markers.current.forEach(m=>m.remove());markers.current=[];
  for(const p of photos){
   if(p.lon===null||p.lat===null)continue;
   const el=document.createElement('button');el.type='button';el.className='photo-marker '+(p.result?.label.startsWith('Suspected')?'alert-marker':'')+(selected===p.id?' selected':'');el.title=p.result?.label||p.status;el.setAttribute('aria-label',`Open image ${p.id}`);el.onclick=e=>{e.stopPropagation();onSelect(p)};
   markers.current.push(new Marker({element:el}).setLngLat([p.lon,p.lat]).addTo(m));
  }
  if(mission&&!drawMode){
   for(const [pt,label] of [[mission.plan.launch,'L'],[mission.plan.return,'R']] as [Position,string][]){
    const el=document.createElement('div');el.className='route-endpoint';el.textContent=label;el.title=label==='L'?'Launch point':'Return point';markers.current.push(new Marker({element:el}).setLngLat(pt).addTo(m));
   }
  }
  if(draft&&!drawMode){
   draft.coordinates[0].slice(0,-1).forEach((pt,i)=>{
    const el=document.createElement('div');el.className='vertex-marker';
    const v=new Marker({element:el,draggable:true}).setLngLat(pt).addTo(m);
    v.on('dragend',()=>{const c=draft.coordinates[0].slice(0,-1).map(p=>[...p] as Position);const pos=v.getLngLat();c[i]=[pos.lng,pos.lat];boundaryCallback.current({type:'Polygon',coordinates:[[...c,c[0]]]});});markers.current.push(v);
   });
  }
 },[ready,farm,draft,mission,photos,selected,exclusions,drawMode]);
 useEffect(()=>{if(!ready||!farm||!map.current)return;const b=new maplibregl.LngLatBounds();farm.boundary.coordinates[0].forEach(p=>b.extend(p));map.current.fitBounds(b,{padding:70,maxZoom:17,duration:700});},[farm?.id,ready]);
 async function search(){
  if(Date.now()-lastSearch.current<1500)return;lastSearch.current=Date.now();setSearching(true);
  try{
   const parts=query.split(',').map(Number);
   if(parts.length===2&&parts.every(Number.isFinite)&&Math.abs(parts[0])<=90&&Math.abs(parts[1])<=180){map.current?.flyTo({center:[parts[1],parts[0]],zoom:15});return;}
   const endpoint=import.meta.env.VITE_GEOCODER_URL||'https://nominatim.openstreetmap.org/search';
   const url=new URL(endpoint);url.searchParams.set('q',query);url.searchParams.set('format','json');url.searchParams.set('limit','1');
   const r=await fetch(url);if(!r.ok)throw new Error('Location provider unavailable. Enter latitude, longitude instead.');
   const data=await r.json();if(!data.length)throw new Error('No matching location. Try latitude, longitude.');map.current?.flyTo({center:[Number(data[0].lon),Number(data[0].lat)],zoom:14});
  }catch(e){onError((e as Error).message)}finally{setSearching(false)}
 }
 return <div className="map-shell"><div ref={container} className="map-canvas"/><form className="map-search" onSubmit={e=>{e.preventDefault();void search()}}><Search size={17}/><input aria-label="Search location" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search a place or lat, lon"/><button disabled={searching||!query}>{searching?'…':'Go'}</button></form>
 <div className="map-top-label"><span className="live-dot"/> FIELD WORKSPACE</div>
 <div className="map-controls"><button aria-label="Zoom in" onClick={()=>map.current?.zoomIn()}><Plus size={18}/></button><button aria-label="Zoom out" onClick={()=>map.current?.zoomOut()}><Minus size={18}/></button><button aria-label="Fit farm" onClick={()=>{if(farm){const b=new maplibregl.LngLatBounds();farm.boundary.coordinates[0].forEach(p=>b.extend(p));map.current?.fitBounds(b,{padding:70})}}}><Crosshair size={18}/></button><button aria-label="Switch map background" onClick={()=>{localStorage.setItem('agriscan-map-style',offline?'https://tiles.openfreemap.org/styles/liberty':'offline');location.reload()}}><Layers size={18}/></button></div>
 {drawMode&&<div className="draw-prompt"><b>{drawMode==='boundary'?'Draw your farm boundary':'Draw an exclusion zone'}</b><span>Click the map to add corners · {vertexCount} points</span><div><button className="secondary" onClick={()=>{points.current.pop();updateDrawing()}}>Undo point</button><button className="primary" disabled={vertexCount<3} onClick={finish}>Finish polygon</button></div></div>}
 {offline&&<div className="map-notice">Map provider unavailable. Switch to offline canvas in Settings; drawing and survey calculations still work.</div>}
 <div className="map-legend"><span><i className="legend-boundary"/>Farm boundary</span><span><i className="legend-route"/>Survey line</span><span><i className="legend-alert"/>Suspected finding</span></div>
 </div>;
}
