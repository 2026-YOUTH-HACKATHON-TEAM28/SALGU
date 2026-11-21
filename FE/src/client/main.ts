import { render } from 'lit-html';
import './styles/main.css';
import { appView } from './components/app.js';
import { afterChatRender, beforeChatRender } from './components/chat.js';
import { boot, subscribe } from './store.js';
import { syncMap } from './map/mapView.js';

const root = document.getElementById('app');
if (!root) throw new Error('#app 이 없어요');

const draw = () => {
  beforeChatRender();
  render(appView(), root);
  afterChatRender();
  syncMap();
};

subscribe(draw);
draw();
void boot();
