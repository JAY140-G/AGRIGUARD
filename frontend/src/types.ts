export type Position=[number,number];
export type Polygon={type:'Polygon';coordinates:Position[][]};
export type Farm={id:string;name:string;crop:string;planting_date:string|null;boundary:Polygon;area_ha:number;area_acres:number};
export type Plan={survey_segments:GeoJSON.LineString[];transit_segments:GeoJSON.LineString[];capture_points:Position[];launch:Position;return:Position;survey_distance_m:number;transit_distance_m:number;duration_s:number;image_count:number;spacing_m:number;camera_coverage:boolean;provisional:boolean;exclusions:Polygon[];warning:string};
export type Mission={id:string;farm_id:string;state:string;plan:Plan;progress:number;created:string;telemetry:{position?:Position;battery_percent?:number;captured?:number;total?:number};error?:string};
export type Photo={id:string;farm_id:string;mission_id:string|null;captured:string;lon:number|null;lat:number|null;location_source:string;metadata:Record<string,string|number>;domain:string;simulated_capture:boolean;status:string;result:{label:string;score:number|null;model_version:string;domain:string;uncertain:boolean;unsupported:boolean;simulated:boolean;analysis_mode:string}|null;feedback:string|null};
export const featureCollection=(features:GeoJSON.Feature[]):GeoJSON.FeatureCollection=>({type:'FeatureCollection',features});
