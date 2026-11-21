import { html, nothing } from 'lit-html';
import { APP_VERSION } from '../../shared/version.js';
import { STAGES } from '../../shared/labels.js';
import { icons, logo } from '../icons.js';
import { confirmAction } from './common.js';
import { deleteChat, login, logout, newChat, openChat, openPanel, refreshList, state, ui } from '../store.js';

function accountButton() {
  const u = state.session?.user;
  if (!u) return nothing;
  const face =
    u.kind === 'guest'
      ? icons.person()
      : u.photo
        ? html`<img src=${u.photo} alt="" width="28" height="28" />`
        : html`<span class="initial">${u.name.slice(0, 1)}</span>`;
  return html`<div class="account">
    <button
      class="icon-btn account-btn"
      aria-haspopup="menu"
      aria-expanded=${state.ui.accountOpen}
      aria-label="내 계정"
      data-testid="account-btn"
      @click=${() => ui({ accountOpen: !state.ui.accountOpen, listOpen: false })}
    >
      ${face}
    </button>
    ${
      state.ui.accountOpen
        ? html`<div class="menu" role="menu" data-testid="account-menu">
            <p class="menu-name">${u.name}</p>
            <p class="menu-sub">
              ${u.kind === 'kakao' ? '카카오 계정' : u.kind === 'mock' ? '예시 계정(카카오 연결 전)' : '둘러보는 중'}
            </p>
            ${
              u.kind === 'guest'
                ? html`<button role="menuitem" class="btn-kakao small" @click=${() => login('mock')}>
                    카카오로 로그인
                  </button>`
                : html`<button role="menuitem" class="btn-ghost" @click=${logout} data-testid="logout">
                    로그아웃
                  </button>`
            }
            <p class="menu-ver">화면 v${APP_VERSION}</p>
          </div>`
        : nothing
    }
  </div>`;
}

function chatList() {
  if (!state.ui.listOpen) return nothing;
  const stageLabel = (id: string) => STAGES.find((s) => s.id === id)?.label ?? '';
  return html`<div class="drawer" role="dialog" aria-label="대화 목록" data-testid="chat-list">
    <div class="drawer-head">
      <h2>대화 목록</h2>
      <button class="icon-btn" aria-label="닫기" @click=${() => ui({ listOpen: false })}>
        ${icons.close()}
      </button>
    </div>
    <p class="drawer-note">이 계정의 대화예요. 지운 대화는 되돌릴 수 없어요.</p>
    <ul>
      ${state.chats.map(
        (c) =>
          html`<li class=${c.id === state.chat?.id ? 'current' : ''}>
            <button class="drawer-item" @click=${() => openChat(c.id)}>
              <span class="title">${c.title}</span>
              <span class="sub"
                >${stageLabel(c.stage)} 단계 · ${new Date(c.updatedAt).toLocaleString('ko-KR')}</span
              >
            </button>
            <button
              class="icon-btn"
              aria-label="${c.title} 지우기"
              @click=${() => {
                if (confirmAction(`'${c.title}' 대화를 지울까요? 지우면 되돌릴 수 없어요.`))
                  void deleteChat(c.id);
              }}
            >
              ${icons.trash(18)}
            </button>
          </li>`,
      )}
    </ul>
  </div>`;
}

export function headerView() {
  const visits = state.schedule.length;
  return html`<header class="top">
    <button class="brand" @click=${newChat} aria-label="살구 첫 화면으로" data-testid="logo">
      <span class="brand-tile">${logo(24)}</span><strong>살구</strong
      ><span class="tagline">살 집 구하기</span>
    </button>
    <nav class="top-actions" aria-label="주요 메뉴">
      <button
        class="hdr-btn"
        @click=${() => openPanel('sched')}
        data-testid="hdr-sched"
        aria-label="일정${visits ? ` ${visits}건` : ''}"
      >
        ${icons.calendar()}<span class="lbl">일정</span>${visits ? html`<i class="count">${visits}</i>` : ''}
      </button>
      <button class="hdr-btn pc-only" @click=${() => openPanel('map')} data-testid="hdr-map">
        ${icons.map()}<span class="lbl">지도</span>
      </button>
      <button
        class="hdr-btn"
        aria-expanded=${state.ui.listOpen}
        aria-label="대화 목록"
        @click=${() => {
          ui({ listOpen: !state.ui.listOpen, accountOpen: false });
          void refreshList();
        }}
        data-testid="hdr-chats"
      >
        ${icons.chats()}<span class="lbl">대화</span>
      </button>
      <button class="hdr-btn" @click=${newChat} data-testid="hdr-new" aria-label="새 대화">
        ${icons.pen()}<span class="lbl">새 대화</span>
      </button>
      ${accountButton()}
    </nav>
    ${chatList()}
  </header>`;
}
