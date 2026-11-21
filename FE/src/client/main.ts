import { render } from 'lit-html';
import './styles/main.css';
import './styles/spec.css';
import { appView } from './components/app.js';
import { afterChatRender, beforeChatRender } from './components/chat.js';
import { boot, subscribe } from './store.js';
import { syncMap } from './map/mapView.js';
import { syncMiniMaps } from './map/miniMaps.js';

const root = document.getElementById('app');
if (!root) throw new Error('#app 이 없어요');

const draw = () => {
  beforeChatRender();
  render(appView(), root);
  afterChatRender();
  syncMap();
  syncMiniMaps();
};

subscribe(draw);
draw();
void boot();
