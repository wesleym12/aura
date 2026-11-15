// Interface propria do modo entalhe (app de mesa). O "motor" da pagina (conversa, voz, palavra de ativacao,
// configuracoes) continua o mesmo do modo janela; aqui so muda o que aparece: menu lateral + uma tela por vez.
(() => {
  const E = (tag, attrs = {}, html = '') => Object.assign(document.createElement(tag), attrs, html ? { innerHTML: html } : {});
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
  const getJSON = (u) => fetch(u).then(r => r.ok ? r.json() : Promise.reject(new Error(r.statusText)));
  const when = (iso) => { try { return new Date(iso.replace(' ', 'T')).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }); } catch { return iso || ''; } };
  const ask = (text) => { show('conversa'); sendText(text); };          // atalhos que viram um pedido para a A.U.R.A.
  const ICON = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
  const I = {
    conversa: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 21l1.9-5.4A8 8 0 1 1 21 12z"/>',
    historico: '<path d="M4 6h16M4 12h16M4 18h10"/>',
    memoria: '<path d="M12 5a3 3 0 0 0-5.9.8A3 3 0 0 0 4 11a3 3 0 0 0 1.5 5.2A3 3 0 0 0 12 18zM12 5a3 3 0 0 1 5.9.8A3 3 0 0 1 20 11a3 3 0 0 1-1.5 5.2A3 3 0 0 1 12 18zM12 5v13"/>',
    agenda: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    agendados: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    musica: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    casa: '<path d="M3 11 12 4l9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-5h4v5"/>',
    pc: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    ajustes: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>',
    recolher: '<path d="M6 15l6-6 6 6"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
  };
  const VIEWS = [['conversa', 'Conversa'], ['historico', 'Histórico'], ['memoria', 'Memória'], ['agenda', 'Agenda'],
    ['agendados', 'Agendados'], ['musica', 'Música'], ['casa', 'Casa'], ['pc', 'Meu PC']];
  const TITLES = Object.fromEntries([...VIEWS, ['ajustes', 'Ajustes']]);
  const FACE = '<span class="np-face" aria-hidden="true"><i class="eye l"></i><i class="eye r"></i><i class="mouth"></i></span>';

  // ---------- esqueleto ----------
  const root = E('div', { id: 'ent' });
  const navBtn = (k, label) => `<button class="e-nav" type="button" data-v="${k}">${ICON(I[k])}<span>${label}</span></button>`;
  root.innerHTML = `
    <aside class="e-side" aria-label="Menu">
      <div class="e-brand">${FACE}<span><b id="e-name">A.U.R.A.</b><small id="e-st">Pronta</small></span></div>
      ${VIEWS.map(([k, l]) => navBtn(k, l)).join('')}
      <span class="e-space"></span>
      ${navBtn('ajustes', 'Ajustes')}
      <button class="e-nav" type="button" id="e-collapse">${ICON(I.recolher)}<span>Recolher</span></button>
    </aside>
    <main class="e-main">
      <div class="e-head"><h2><i></i><span id="e-title">Conversa</span></h2><div class="e-tools" id="e-tools"></div></div>
      <section class="e-view e-flex" data-v="conversa" id="e-conv"></section>
      ${VIEWS.slice(1).map(([k]) => `<section class="e-view" data-v="${k}"></section>`).join('')}
      <section class="e-view" data-v="ajustes"></section>
    </main>`;
  document.body.appendChild(root);
  const $v = (k) => root.querySelector(`.e-view[data-v="${k}"]`);
  const tools = root.querySelector('#e-tools');

  // a conversa usa as mesmas mensagens e caixa de texto do modo janela (mudam so de lugar)
  const conv = $v('conversa');
  conv.append($('log'), $('attach-row'), $('f'));

  // ---------- navegacao ----------
  let cur = 'conversa';
  function show(k) {
    cur = k;
    root.querySelectorAll('.e-nav[data-v]').forEach(b => b.classList.toggle('on', b.dataset.v === k));
    root.querySelectorAll('.e-view').forEach(v => v.classList.toggle('on', v.dataset.v === k));
    root.querySelector('#e-title').textContent = TITLES[k];
    tools.innerHTML = '';
    (R[k] || (() => {}))();
  }
  root.querySelectorAll('.e-nav[data-v]').forEach(b => b.onclick = () => show(b.dataset.v));
  root.querySelector('#e-collapse').onclick = () => notchCollapse();
  window.entShow = show;

  // nome e estado no topo do menu
  setInterval(() => {
    root.querySelector('#e-name').textContent = $('hdr-name').textContent;
    const st = document.body.dataset.state, sleep = document.body.hasAttribute('data-sleep');
    root.querySelector('#e-st').textContent = sleep ? 'Dormindo' : ({ listening: 'Ouvindo', thinking: 'Pensando', speaking: 'Falando' })[st] || 'Pronta';
    if (cur === 'pc') renderPcTiles();
  }, 1000);

  const tool = (html, onclick, cls = 'e-btn') => { const b = E('button', { type: 'button', className: cls }, html); b.onclick = onclick; tools.append(b); return b; };
  const empty = (title, text) => `<div class="e-empty"><b>${title}</b>${text}</div>`;
  const fail = (el, e) => { el.innerHTML = empty('Não consegui carregar', esc(e.message)); };

  // ---------- telas ----------
  const R = {
    conversa() {
      const wake = tool(`${ICON(I.mic)}Sempre ouvindo`, () => { $('wake-btn').click(); setTimeout(sync, 400); });
      const sync = () => wake.classList.toggle('on', $('wake-btn').getAttribute('aria-pressed') === 'true');
      sync();
      tool(ICON(I.mic), () => $('mic-btn').click(), 'e-btn e-icon').title = 'Falar agora';
      tool(`${ICON(I.plus)}Nova`, () => newConv()).title = 'Nova conversa';
      setTimeout(() => $('t').focus(), 50);
    },

    async historico() {
      const el = $v('historico');
      el.innerHTML = '<input class="e-input" id="e-hq" placeholder="Procurar nas conversas..."><div class="e-list" id="e-hl"></div>';
      let all = [];
      const draw = () => {
        const q = el.querySelector('#e-hq').value.trim().toLowerCase();
        const items = all.filter(c => !q || (c.title || '').toLowerCase().includes(q));
        el.querySelector('#e-hl').innerHTML = items.length ? items.map(c => `<div class="e-item click" data-id="${esc(c.id)}">
            <div class="e-txt"><b>${esc(c.title || 'Conversa')}</b><small>${esc(when(c.updated))}</small></div></div>`).join('')
          : empty('Nenhuma conversa', q ? 'Nada com esse nome.' : 'As conversas aparecem aqui.');
        el.querySelectorAll('.e-item').forEach(r => r.onclick = async () => { await openConv(r.dataset.id); show('conversa'); });
      };
      el.querySelector('#e-hq').oninput = draw;
      tool(`${ICON(I.plus)}Nova conversa`, () => { newConv(); show('conversa'); });
      try { all = await getJSON('/api/conversations'); draw(); } catch (e) { fail(el.querySelector('#e-hl'), e); }
    },

    async memoria() {
      const el = $v('memoria');
      el.innerHTML = `<div class="e-row"><input class="e-input" id="e-mq" placeholder="Buscar por significado... (ex.: meu time)"></div>
        <div class="e-chips" id="e-mk"></div><div class="e-list" id="e-ml"></div>
        <div class="e-sec">Guardar algo</div>
        <form class="e-row" id="e-mf"><input class="e-input" id="e-mt" placeholder="Algo importante que ela deve lembrar..."><button class="e-btn acc">Guardar</button></form>`;
      let kind = '', timer = 0;
      const load = async () => {
        const q = el.querySelector('#e-mq').value.trim();
        try {
          const j = await getJSON(`/api/memory?q=${encodeURIComponent(q)}&kind=${encodeURIComponent(kind)}`);
          const total = Object.values(j.counts || {}).reduce((a, b) => a + b, 0);
          el.querySelector('#e-mk').innerHTML = [['', 'Tudo', total], ...Object.entries(j.kinds || {}).map(([k, l]) => [k, l, (j.counts || {})[k] || 0])]
            .map(([k, l, n]) => `<button type="button" class="e-chip${k === kind ? ' on' : ''}" data-k="${k}">${esc(l)} ${n}</button>`).join('');
          el.querySelectorAll('.e-chip').forEach(c => c.onclick = () => { kind = c.dataset.k; load(); });
          el.querySelector('#e-ml').innerHTML = j.items.length ? j.items.map(n => `<div class="e-item">
              <div class="e-txt"><b>${esc(n.title || n.content)}</b>${n.title ? `<p>${esc(n.content)}</p>` : ''}
              <small>${esc((j.kinds || {})[n.kind] || n.kind)} · ${esc(when(n.created))}${n.conv_title ? ' · ' + esc(n.conv_title) : ''}</small></div>
              <button class="e-x" type="button" data-id="${n.id}" title="Esquecer">✕</button></div>`).join('')
            : empty(q ? 'Nada encontrado' : 'Memória vazia', q ? 'Tente outras palavras.' : 'O que ela aprender sobre você aparece aqui.');
          el.querySelectorAll('.e-x').forEach(b => b.onclick = async () => {
            if (!confirm('Esquecer esta lembrança?')) return;
            await fetch(`/api/memory/${b.dataset.id}`, { method: 'DELETE' }); load();
          });
        } catch (e) { fail(el.querySelector('#e-ml'), e); }
      };
      el.querySelector('#e-mq').oninput = () => { clearTimeout(timer); timer = setTimeout(load, 350); };
      el.querySelector('#e-mf').onsubmit = (ev) => {
        ev.preventDefault(); const v = el.querySelector('#e-mt').value.trim(); if (!v) return;
        el.querySelector('#e-mt').value = ''; ask(`Guarde na memória: ${v}`);
      };
      load();
    },

    async agenda() {
      const el = $v('agenda');
      el.innerHTML = '<div class="e-list" id="e-al"></div>';
      tool('Hoje e próximos 7 dias', () => {}, 'e-btn').disabled = true;
      try {
        const j = await getJSON('/api/agenda?days=7');
        if (!j.connected) {
          el.innerHTML = empty('Google Agenda não conectado', 'Conecte em Ajustes → "Todas as configurações" → Conectores → Google.');
          return;
        }
        let day = '';
        el.querySelector('#e-al').innerHTML = j.events.length ? j.events.map(ev => {
          const d = new Date(ev.start), dl = d.toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: '2-digit' });
          const head = dl !== day ? `<div class="e-sec">${esc(dl)}</div>` : ''; day = dl;
          const h = ev.all_day ? 'dia todo' : d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
          return `${head}<div class="e-item"><span class="e-tag">${h}</span><div class="e-txt"><b>${esc(ev.title)}</b>${ev.location ? `<small>${esc(ev.location)}</small>` : ''}</div></div>`;
        }).join('') : empty('Nada marcado', 'Nenhum compromisso nos próximos 7 dias.');
      } catch (e) { fail(el, e); }
      tool(`${ICON(I.plus)}Marcar`, () => { show('conversa'); $('t').value = 'Marca na agenda: '; $('t').focus(); });
    },

    async agendados() {
      const el = $v('agendados');
      tool(`${ICON(I.plus)}Novo`, () => { show('conversa'); $('t').value = 'Todo dia às 8h, '; $('t').focus(); }).title = 'Peça em linguagem natural';
      const load = async () => {
        try {
          const list = await getJSON('/api/schedules');
          const kinds = { once: 'uma vez', daily: 'todo dia', weekly: 'toda semana', interval: 'a cada' };
          el.innerHTML = list.length ? `<div class="e-list">${list.map(s => `<div class="e-item">
              <span class="e-tag${s.enabled ? ' ok' : ''}">${s.enabled ? 'ativo' : 'pausado'}</span>
              <div class="e-txt"><b>${esc(s.title)}</b><small>${esc(kinds[s.kind] || s.kind)} ${esc(s.kind === 'interval' ? s.every + ' min' : s.at)}${s.next_run ? ' · próximo: ' + esc(when(s.next_run)) : ''}</small></div>
              <button class="e-btn" type="button" data-run="${esc(s.id)}">Rodar</button>
              <button class="e-x" type="button" data-del="${esc(s.id)}" title="Apagar">✕</button></div>`).join('')}</div>`
            : empty('Nenhum agendamento', 'Peça na conversa, por exemplo: "todo dia às 8h me dá a previsão do tempo".');
          el.querySelectorAll('[data-run]').forEach(b => b.onclick = async () => { b.disabled = true; await fetch(`/api/schedules/${b.dataset.run}/run`, { method: 'POST' }); b.textContent = 'Rodando…'; });
          el.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
            if (!confirm('Apagar este agendamento?')) return;
            await fetch(`/api/schedules/${b.dataset.del}`, { method: 'DELETE' }); load();
          });
        } catch (e) { fail(el, e); }
      };
      load();
    },

    async musica() {
      const el = $v('musica');
      try {
        const j = await getJSON('/api/spotify');
        if (!j.configured || !j.user) {
          el.innerHTML = empty('Spotify não conectado', 'Conecte em Ajustes → "Todas as configurações" → Plugins → Spotify (precisa de Premium).');
          return;
        }
        el.innerHTML = `<div class="e-sec">Conta: ${esc(j.user)}</div>
          <div class="e-grid">
            <div class="e-tile click" data-a="volta a música anterior no Spotify"><small>ANTERIOR</small><b>⏮</b></div>
            <div class="e-tile click" data-a="pausa ou continua a música do Spotify"><small>PAUSAR / TOCAR</small><b>⏯</b></div>
            <div class="e-tile click" data-a="pula para a próxima música no Spotify"><small>PRÓXIMA</small><b>⏭</b></div>
            <div class="e-tile click" data-a="o que está tocando no Spotify?"><small>TOCANDO</small><b>♪</b></div>
          </div>
          <div class="e-sec">Tocar</div>
          <form class="e-row" id="e-sf"><input class="e-input" id="e-st2" placeholder="Música, artista ou playlist..."><button class="e-btn acc">Tocar</button></form>
          ${(j.devices || []).length ? `<div class="e-sec">Aparelhos</div><div class="e-list">${j.devices.map(d => `<div class="e-item"><div class="e-txt"><b>${esc(d.name)}</b></div>${d.is_active ? '<span class="e-tag ok">tocando aqui</span>' : ''}</div>`).join('')}</div>` : ''}`;
        el.querySelectorAll('[data-a]').forEach(t => t.onclick = () => ask(t.dataset.a));
        el.querySelector('#e-sf').onsubmit = (ev) => { ev.preventDefault(); const v = el.querySelector('#e-st2').value.trim(); if (v) ask(`Toca ${v} no Spotify`); };
      } catch (e) { fail(el, e); }
    },

    async casa() {
      const el = $v('casa');
      try {
        const j = await getJSON('/api/casa');
        if (!j.configured) {
          el.innerHTML = empty('Casa inteligente não conectada', 'Conecte o Home Assistant em Ajustes → "Todas as configurações" → Plugins → Casa inteligente.');
          return;
        }
        const ents = (await getJSON('/api/casa/entities')).filter(e => !e.hidden && ['light', 'switch', 'fan', 'cover', 'climate', 'media_player', 'lock'].includes(e.domain));
        const areas = {};
        ents.forEach(e => (areas[e.area || 'Sem cômodo'] ||= []).push(e));
        el.innerHTML = ents.length ? Object.entries(areas).map(([a, list]) => `<div class="e-sec">${esc(a)}</div><div class="e-grid">${list.map(e => `
            <div class="e-tile click" data-n="${esc(e.name)}" data-on="${e.state === 'on' || e.state === 'open' || e.state === 'playing'}">
              <small>${esc(e.name)}</small><b>${esc(({ on: 'Ligado', off: 'Desligado', open: 'Aberto', closed: 'Fechado', locked: 'Trancado', unlocked: 'Destrancado' })[e.state] || e.state)}</b></div>`).join('')}</div>`).join('')
          : empty('Nenhum aparelho', 'Os aparelhos do Home Assistant aparecem aqui.');
        el.querySelectorAll('[data-n]').forEach(t => t.onclick = () => ask(`${t.dataset.on === 'true' ? 'Desliga' : 'Liga'} ${t.dataset.n}`));
      } catch (e) { fail(el, e); }
      tool('Atualizar', () => show('casa'));
    },

    pc() {
      const el = $v('pc');
      el.innerHTML = `<div class="e-grid" id="e-pt"></div>
        <div class="e-set"><span>Controle do computador<small>Abrir programas e sites, ler a tela e, com o seu Autorizar, clicar e digitar.</small></span>
          <button class="e-switch" type="button" id="e-pcc" aria-pressed="false"></button></div>
        <div class="e-sec">Atalhos</div>
        <div class="e-row" style="flex-wrap:wrap">
          <button class="e-btn" type="button" data-a="Tira um print da tela">Tirar print</button>
          <button class="e-btn" type="button" data-a="Quais janelas estão abertas?">Janelas abertas</button>
          <button class="e-btn" type="button" data-a="Bloqueia o computador">Bloquear o PC</button>
        </div>`;
      el.querySelector('#e-pcc').onclick = () => { $('pc-btn').click(); setTimeout(renderPcTiles, 600); };
      el.querySelectorAll('[data-a]').forEach(b => b.onclick = () => ask(b.dataset.a));
      renderPcTiles();
    },

    async ajustes() {
      const el = $v('ajustes');
      const info = desk.api ? await desk.api.info() : { mode: 'entalhe', on_top: false };
      const sw = (id, on) => `<button class="e-switch" type="button" id="${id}" aria-pressed="${!!on}"></button>`;
      el.innerHTML = `
        <div class="e-set"><span>Modo de exibição<small>Entalhe: esta pílula no topo da tela. Janela: a A.U.R.A. numa janela comum.</small></span>
          <span class="e-seg"><button type="button" data-m="entalhe" class="${info.mode === 'entalhe' ? 'on' : ''}">Entalhe</button><button type="button" data-m="janela" class="${info.mode === 'janela' ? 'on' : ''}">Janela</button></span></div>
        <div class="e-set"><span>Acima das janelas<small>Ligado: sempre visível, mesmo com programa maximizado. Desligado: some nesses casos.</small></span>${sw('e-top', info.on_top)}</div>
        <div class="e-set"><span>Sempre ouvindo<small>Atende quando você diz "${esc(cfg.wake_word || 'Aura')}".</small></span>${sw('e-wake', $('wake-btn').getAttribute('aria-pressed') === 'true')}</div>
        <div class="e-set"><span>Modo conversa<small>Depois de responder, continua ouvindo por 2 minutos sem precisar do nome.</small></span>${sw('e-convo', cfg.conversation_mode === true)}</div>
        <div class="e-set"><span>Aprender sozinha<small>Guarda fatos duradouros sobre você que aparecem nas conversas.</small></span>${sw('e-learn', cfg.auto_learn !== false)}</div>
        <div class="e-set"><span>Nome da assistente</span><input class="e-input" style="max-width:220px" id="e-an" maxlength="40" value="${esc(cfg.assistant_name)}"></div>
        <div class="e-set"><span>Palavra de ativação</span><input class="e-input" style="max-width:220px" id="e-ww" maxlength="40" value="${esc(cfg.wake_word)}"></div>
        <div class="e-set"><span>Todas as configurações<small>Modelos, voz, contas, conectores, plugins, backups... (abre a A.U.R.A. no modo janela)</small></span>
          <button class="e-btn" type="button" id="e-full">Abrir</button></div>
        <div class="e-set"><span>Encerrar a A.U.R.A.<small>Desliga todos os serviços dela.</small></span>
          <button class="e-btn e-danger" type="button" id="e-quit">Encerrar</button></div>`;
      const flip = (b) => { const on = b.getAttribute('aria-pressed') !== 'true'; b.setAttribute('aria-pressed', String(on)); return on; };
      el.querySelectorAll('[data-m]').forEach(b => b.onclick = () => desk.api?.set_mode(b.dataset.m));
      el.querySelector('#e-top').onclick = (e) => desk.api?.set_on_top(flip(e.currentTarget));
      el.querySelector('#e-wake').onclick = (e) => { flip(e.currentTarget); $('wake-btn').click(); };
      el.querySelector('#e-convo').onclick = (e) => saveSettings({ conversation_mode: flip(e.currentTarget) });
      el.querySelector('#e-learn').onclick = (e) => saveSettings({ auto_learn: flip(e.currentTarget) });
      el.querySelector('#e-an').onchange = (e) => e.target.value.trim() && saveSettings({ assistant_name: e.target.value.trim() });
      el.querySelector('#e-ww').onchange = (e) => e.target.value.trim() && saveSettings({ wake_word: e.target.value.trim() });
      el.querySelector('#e-full').onclick = () => desk.api ? desk.api.set_mode('janela') : openSettings();
      el.querySelector('#e-quit').onclick = () => $('cfg-quit').click();
    },
  };

  function renderPcTiles() {
    const el = $v('pc').querySelector('#e-pt'); if (!el) return;
    const v = (id) => $(id)?.textContent || '--';
    el.innerHTML = [['CPU', 'v-cpu'], ['RAM', 'v-ram'], ['GPU', 'v-gpu'], ['TEMP', 'v-temp'], ['REDE', 'v-net']]
      .map(([k, id]) => `<div class="e-tile"><small>${k}</small><b>${esc(v(id))}</b></div>`).join('');
    $v('pc').querySelector('#e-pcc')?.setAttribute('aria-pressed', String($('pc-btn').getAttribute('aria-pressed') === 'true'));
  }

  show('conversa');
})();
