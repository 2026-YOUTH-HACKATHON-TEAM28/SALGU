/* 화면 동작 시험(e2e)용 가짜 대화 에이전트 서버. playwright 가 화면 서버와 함께 띄워요. */
import { createServer } from 'node:http';
import { fakeAgentReply } from './fakeChatAgent.js';

const port = Number(process.env.FAKE_AGENT_PORT || 8796);

createServer((req, res) => {
  const send = (body: unknown) => {
    res.writeHead(200, { 'content-type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify(body));
  };
  if (req.method === 'GET' && req.url === '/health') return send({ ok: true });
  let raw = '';
  req.setEncoding('utf8');
  req.on('data', (c: string) => (raw += c));
  req.on('end', () => {
    const body = (raw ? JSON.parse(raw) : {}) as { session_id?: string; message?: string };
    if (req.url === '/api/reset') return send({ ok: true });
    send(fakeAgentReply(body.session_id ?? 's', body.message ?? ''));
  });
}).listen(port, '127.0.0.1');
