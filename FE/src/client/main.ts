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

// 화면 틀(대화·지도)에서는 페이지 자체가 스크롤되면 안 돼요(스크롤은 대화 칸 안에서만).
// 입력칸 포커스 등으로 브라우저가 페이지를 밀어 올리면 바로 되돌려요.
window.addEventListener(
  'scroll',
  () => {
    if ((window.scrollY || window.scrollX) && document.querySelector('.shell')) window.scrollTo(0, 0);
  },
  { passive: true },
);

subscribe(draw);
draw();
void boot();
