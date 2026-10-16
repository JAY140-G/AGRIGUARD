/// <reference types="vite/client" />
interface ImportMetaEnv {
  readonly VITE_MAPTILER_API_KEY?: string;
  readonly VITE_GOOGLE_MAPS_API_KEY?: string;
  readonly VITE_MAP_STYLE?: string;
  readonly VITE_GEOCODER_URL?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
