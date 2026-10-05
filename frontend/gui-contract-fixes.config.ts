// Isolated browser acceptance: all API calls go to the synthetic-only app.
import { defineConfig, mergeConfig } from 'vite';
import base from './vite.config';
export default mergeConfig(base, defineConfig({server:{proxy:{
  '/api':{target:'http://127.0.0.1:8002',changeOrigin:true},
  '/ws':{target:'http://127.0.0.1:8002',ws:true},
  '/ui':{target:'http://127.0.0.1:8002',changeOrigin:true},
}}}));
