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
    ear: '<path d="M6 8.5a6.5 6.5 0 1 1 13 0c0 6-6 6-6 10a3.5 3.5 0 1 1-7 0"/><path d="M15 8.5a2.5 2.5 0 0 0-5 0v1a2 2 0 1 1 0 4"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    prev: '<path d="M19 20 9 12l10-8z"/><path d="M5 19V5"/>',
    next: '<path d="m5 4 10 8-10 8z"/><path d="M19 5v14"/>',
    play: '<path d="m7 4 13 8-13 8z"/>',
    pause: '<path d="M8 5v14M16 5v14"/>',
    vol: '<path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/>',
    mute: '<path d="M11 5 6 9H3v6h3l5 4z"/><path d="m22 9-6 6M16 9l6 6"/>',
    tarefas: '<path d="M9 11l3 3 8-8"/><path d="M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9"/>',
    timers: '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2 2M9 2h6"/>',
    habitos: '<path d="M12 2.7c3 3.5 6 6.9 6 10.3a6 6 0 0 1-12 0c0-3.4 3-6.8 6-10.3z"/>',
    textos: '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M4 16V5a2 2 0 0 1 2-2h11"/>',
    rotina: '<path d="M9 11l3 3 8-8"/><path d="M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9"/>',
    apps: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    biblioteca: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/>',
  };
  // menu lateral curto; cada grupo tem as suas telas em abas (submenu)
  const VIEWS = [['conversa', 'Início'], ['rotina', 'Rotina'], ['apps', 'Apps'], ['biblioteca', 'Biblioteca']];
  const GROUPS = {
    rotina: [['tarefas', 'Tarefas'], ['timers', 'Timers'], ['habitos', 'Hábitos'], ['agendados', 'Agendados']],
    apps: [['agenda', 'Agenda'], ['musica', 'Música'], ['casa', 'Casa'], ['pc', 'Meu PC']],
    biblioteca: [['historico', 'Histórico'], ['textos', 'Textos']],
  };
  const tab = { rotina: 'tarefas', apps: 'agenda', biblioteca: 'historico' };
  const groupOf = (k) => Object.keys(GROUPS).find(g => GROUPS[g].some(([x]) => x === k));
  const at = (k) => cur === groupOf(k) && tab[groupOf(k)] === k;          // essa aba esta aberta agora?
  const open = (k) => { const g = groupOf(k); if (g) { tab[g] = k; show(g); } else show(k); };
  let cur = 'conversa';
  const TITLES = Object.fromEntries([...VIEWS, ['ajustes', 'Ajustes']]);
  const FACE = '<span class="np-face" aria-hidden="true"><i class="eye l"></i><i class="eye r"></i><i class="mouth"></i><b class="np-acc"></b></span>';

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
  const $v = (k) => root.querySelector(`.e-view[data-v="${k}"], .e-sub[data-v="${k}"]`);
  const tools = root.querySelector('#e-tools');

  // Inicio: conversa (as mesmas mensagens e caixa de texto do modo janela, so mudam de lugar) + coluna "agora"
  // com o que esta tocando (e, nas proximas fases, timers, tarefas e habitos)
  const conv = $v('conversa');
  conv.innerHTML = `<div class="e-home"><div class="e-chat fresh"><div class="e-hello" id="e-hello"></div></div>
    <aside class="e-aside"><div class="e-card e-now"><div id="e-player"></div><div id="e-extra"></div></div></aside></div>`;
  const chat = conv.querySelector('.e-chat');
  chat.append($('log'), $('attach-row'), $('f'));
  // conversa vazia: em vez da lista de mensagens, uma saudacao com 4 sugestoes; com mensagens, so a conversa
  const syncFresh = () => {
    const fresh = !$('log').querySelector('.entry');
    if (fresh && !chat.classList.contains('fresh')) drawSugs();
    chat.classList.toggle('fresh', fresh);
  };
  new MutationObserver(syncFresh).observe($('log'), { childList: true });
  // sugestoes clicaveis (cada fase acrescenta as suas em window.entSugs)
  window.entSugs = ['vai chover hoje?', 'quanto está o dólar?', 'timer de 5 minutos', 'me lembra de alongar em 1 hora',
    'bebi um copo de água', 'notícias de hoje', 'como está meu PC?', 'toca uma música', 'quanto é 15% de 230?',
    'organiza minha área de trabalho', 'cara ou coroa', 'quantos dias faltam pro Natal?'];
  function drawSugs() {
    const box = conv.querySelector('#e-hello');
    const pick = [...window.entSugs].sort(() => Math.random() - 0.5).slice(0, 4);
    const d0 = new Date().toLocaleDateString('pt-BR', { weekday: 'long', day: 'numeric', month: 'long' });
    const day = d0.charAt(0).toUpperCase() + d0.slice(1);              // "Segunda-feira, 16 de novembro"
    box.innerHTML = `${FACE}<h3>${esc(greeting())}${cfg.user_name ? ', ' + esc(cfg.user_name) : ''}</h3><small>${esc(day)}</small>
      <p>Fale ou escreva o que precisa. Algumas ideias:</p>
      <div class="e-sugs">${pick.map(t => `<button type="button" class="e-chip" data-s="${esc(t)}">${esc(t)}</button>`).join('')}</div>`;
    box.querySelectorAll('[data-s]').forEach(b => b.onclick = () => sendText(b.dataset.s));
  }
  window.entDrawSugs = drawSugs;
  drawSugs(); setTimeout(syncFresh, 0);

  // ---------- navegacao ----------
  function show(k) {
    if (groupOf(k)) { tab[groupOf(k)] = k; k = groupOf(k); }
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
    if (at('pc')) renderPcTiles();
  }, 1000);

  const tool = (html, onclick, cls = 'e-btn') => { const b = E('button', { type: 'button', className: cls }, html); b.onclick = onclick; tools.append(b); return b; };
  const empty = (title, text) => `<div class="e-empty"><b>${title}</b>${text}</div>`;
  const fail = (el, e) => { el.innerHTML = empty('Não consegui carregar', esc(e.message)); };

  // ---------- telas ----------
  const R = {
    conversa() {
      const wake = tool(`${ICON(I.ear)}Sempre ouvindo`, () => { $('wake-btn').click(); setTimeout(sync, 400); });
      const sync = () => wake.classList.toggle('on', $('wake-btn').getAttribute('aria-pressed') === 'true');
      sync();
      tool(ICON(I.mic), () => $('mic-btn').click(), 'e-btn e-icon').title = 'Falar agora';
      tool(`${ICON(I.plus)}Nova`, () => newConv()).title = 'Nova conversa';
      setTimeout(() => $('t').focus(), 50);
    },

    rotina() { group('rotina'); },
    apps() { group('apps'); },
    biblioteca() { group('biblioteca'); },

    async ajustes() {
      // as MESMAS configuracoes do modo janela (o mesmo conteudo, com abas em cima em vez do menu lateral):
      // mudar aqui ou la e a mesma coisa, sem trocar de modo
      const el = $v('ajustes');
      if (!el.dataset.ready) {
        el.dataset.ready = '1';
        // os mesmos grupos do menu do modo janela
        const groups = [];
        for (const n of document.querySelectorAll('#cfg-back .cfg-nav > .cfg-grp, #cfg-back .cfg-nav > .tab')) {
          if (n.classList.contains('cfg-grp')) groups.push({ name: n.textContent.trim(), tabs: [] });
          else if (groups.length) groups.at(-1).tabs.push(n);
        }
        el.innerHTML = `<div class="e-tabs e-cfggrp" role="tablist">${groups.map((g, i) => `<button type="button" data-grp="${i}">${esc(g.name)}</button>`).join('')}</div>`
          + groups.map((g, i) => `<div class="e-tabs e-cfgtabs" data-grpv="${i}" role="tablist">${g.tabs.map(t => `<button type="button" role="tab" data-tab="${t.dataset.tab}">${t.innerHTML}</button>`).join('')}</div>`).join('');
        el.append(document.querySelector('#cfg-back .cfg-main'));
        el.querySelectorAll('[data-tab]').forEach(b => b.onclick = () => { showPane(b.dataset.tab); markCfg(); });
        el.querySelectorAll('[data-grp]').forEach(b => b.onclick = () => {
          showPane(el.querySelector(`[data-grpv="${b.dataset.grp}"] [data-tab]`).dataset.tab); markCfg();
        });
      }
      try { cfgVoices = await fetch(VOICE_HTTP + '/voices').then(r => r.json()); } catch { cfgVoices = []; }
      await loadLiveStatus();
      renderSettings(); renderMotorTab(); renderMemTab(); renderBackups();
      showPane(document.querySelector('#cfg-back .cfg-nav .tab.active')?.dataset.tab || 'geral');
      markCfg();
    },

    tarefas() {
      const el = $v('tarefas');
      el.innerHTML = `<form class="e-row" id="e-tf"><input class="e-input" id="e-tt" maxlength="200" placeholder="Nova tarefa... (Enter para adicionar)">
          <select class="e-input e-sel" id="e-tp"><option value="alta">Alta</option><option value="media" selected>Média</option><option value="baixa">Baixa</option></select>
          <button class="e-btn acc">Adicionar</button></form>
        <div class="e-list" id="e-tl"></div>`;
      el.querySelector('#e-tf').onsubmit = async (ev) => {
        ev.preventDefault(); const t = el.querySelector('#e-tt'); if (!t.value.trim()) return;
        await rot.post('/api/tasks', { title: t.value.trim(), priority: el.querySelector('#e-tp').value }); t.value = ''; rot.refresh();
      };
      tool('Concluídas somem no fim do dia', () => {}, 'e-btn').disabled = true;
      drawTasks(); setTimeout(() => el.querySelector('#e-tt').focus(), 50);
    },

    timers() {
      const el = $v('timers');
      el.innerHTML = `<div class="e-sec">Começar</div>
        <div class="e-row" style="flex-wrap:wrap">${[1, 5, 10, 15, 25, 30, 60].map(m => `<button class="e-btn" type="button" data-min="${m}">${m < 60 ? m + ' min' : '1 h'}</button>`).join('')}</div>
        <form class="e-row" id="e-xf" style="margin-top:8px"><input class="e-input" id="e-xn" maxlength="60" placeholder="Para quê? (ex.: pizza)">
          <input class="e-input e-num" id="e-xm" type="number" min="0.1" step="0.5" value="10" title="minutos"><span class="e-dim">min</span>
          <button class="e-btn acc">Começar</button></form>
        <div class="e-row" style="margin-top:8px;flex-wrap:wrap">
          <button class="e-btn" type="button" id="e-foco">🎯 Foco 25 min + pausa 5</button>
          <button class="e-btn" type="button" id="e-crono">⏱ Cronômetro</button></div>
        <div class="e-sec">Correndo</div><div class="e-list" id="e-xl"></div>`;
      const start = (secs, label = '', kind = 'timer', then_break = 0) => rot.post('/api/timers', { seconds: secs, label, kind, then_break }).then(rot.refresh);
      el.querySelectorAll('[data-min]').forEach(b => b.onclick = () => start(+b.dataset.min * 60, el.querySelector('#e-xn').value.trim()));
      el.querySelector('#e-xf').onsubmit = (ev) => { ev.preventDefault(); start(+el.querySelector('#e-xm').value * 60, el.querySelector('#e-xn').value.trim()); };
      el.querySelector('#e-foco').onclick = () => start(25 * 60, 'Foco', 'foco', 5);
      el.querySelector('#e-crono').onclick = () => rot.post('/api/timers', { kind: 'cronometro' }).then(rot.refresh);
      drawTimers();
    },

    habitos() {
      const el = $v('habitos');
      el.innerHTML = `<div class="e-grid e-hgrid" id="e-hg"></div>
        <div class="e-sec">Novo hábito</div>
        <form class="e-row" id="e-hf"><input class="e-input" id="e-hn" maxlength="40" placeholder="Nome (ex.: Leitura)">
          <input class="e-input e-num" id="e-hm" type="number" min="1" value="1" title="meta por dia">
          <input class="e-input" id="e-hu" maxlength="20" placeholder="unidade (páginas, min...)" style="max-width:170px">
          <button class="e-btn acc">Criar</button></form>
        <div class="e-set"><span>Lembrete de pausa<small>A cada 50 minutos, o entalhe lembra de levantar, alongar e beber água.</small></span>
          <button class="e-switch" type="button" id="e-brk" aria-pressed="${breakOn()}"></button></div>`;
      el.querySelector('#e-hf').onsubmit = async (ev) => {
        ev.preventDefault(); const n = el.querySelector('#e-hn'); if (!n.value.trim()) return;
        await rot.post('/api/habits', { name: n.value.trim(), target: +el.querySelector('#e-hm').value || 1, unit: el.querySelector('#e-hu').value.trim() });
        n.value = ''; rot.refresh();
      };
      el.querySelector('#e-brk').onclick = (e) => { const on = e.currentTarget.getAttribute('aria-pressed') !== 'true'; e.currentTarget.setAttribute('aria-pressed', String(on)); setBreak(on); };
      drawHabits();
    },

    textos() {
      const el = $v('textos');
      const items = () => cfg.quick_texts || [];
      const copy = async (text, btn) => {
        try { await navigator.clipboard.writeText(text); } catch { const t = E('textarea', { value: text }); document.body.append(t); t.select(); document.execCommand('copy'); t.remove(); }
        if (btn) { const o = btn.textContent; btn.textContent = 'Copiado!'; setTimeout(() => btn.textContent = o, 1200); }
      };
      const draw = () => {
        el.innerHTML = `<div class="e-sec">Textos prontos</div>
          <div class="e-list">${items().length ? items().map((t, i) => `<div class="e-item">
              <div class="e-txt"><b>${esc(t.name)}</b><p>${esc(t.text)}</p></div>
              <button class="e-btn" type="button" data-cp="${i}">Copiar</button>
              <button class="e-x" type="button" data-rm="${i}" title="Apagar">✕</button></div>`).join('')
            : empty('Nenhum texto salvo', 'Salve o seu Pix, endereço, assinatura de e-mail... e peça "copia meu pix".')}</div>
          <form class="e-row" id="e-qf" style="margin-top:8px"><input class="e-input" id="e-qn" maxlength="40" placeholder="Nome (ex.: pix)" style="max-width:170px">
            <input class="e-input" id="e-qt" maxlength="2000" placeholder="Texto"><button class="e-btn acc">Salvar</button></form>
          <div class="e-set"><span>Histórico do que você copiou<small>Guarda os últimos 25 textos copiados só na memória deste PC (some ao reiniciar). Desligado: nada é guardado.</small></span>
            <button class="e-switch" type="button" id="e-clip" aria-pressed="${cfg.clip_history === true}"></button></div>
          <div class="e-list" id="e-cl"></div>`;
        el.querySelectorAll('[data-cp]').forEach(b => b.onclick = () => copy(items()[+b.dataset.cp].text, b));
        el.querySelectorAll('[data-rm]').forEach(b => b.onclick = async () => {
          if (!confirm(`Apagar o texto "${items()[+b.dataset.rm].name}"?`)) return;
          await saveSettings({ quick_texts: items().filter((_, i) => i !== +b.dataset.rm) }); draw();
        });
        el.querySelector('#e-qf').onsubmit = async (ev) => {
          ev.preventDefault(); const n = el.querySelector('#e-qn').value.trim(), t = el.querySelector('#e-qt').value;
          if (!n || !t.trim()) return;
          await saveSettings({ quick_texts: [...items().filter(x => x.name.toLowerCase() !== n.toLowerCase()), { name: n, text: t }] }); draw();
        };
        el.querySelector('#e-clip').onclick = async (e) => { await saveSettings({ clip_history: cfg.clip_history !== true }); draw(); };
        drawClips();
      };
      async function drawClips() {
        const box = el.querySelector('#e-cl'); if (!box || cfg.clip_history !== true || !LOCAL_PAGE) { if (box) box.innerHTML = ''; return; }
        let list = [];
        try { list = await fetch('http://127.0.0.1:8766/clip?on=1', { cache: 'no-store' }).then(r => r.json()); } catch {}
        box.innerHTML = (list.length ? `<div class="e-row" style="justify-content:space-between"><span class="e-dim">${list.length} copiado(s)</span>
            <button class="e-btn" type="button" id="e-clr">Limpar</button></div>` + list.map((t, i) => `<div class="e-item"><div class="e-txt"><p>${esc(t)}</p></div>
            <button class="e-btn" type="button" data-cc="${i}">Copiar</button></div>`).join('')
          : empty('Nada copiado ainda', 'Copie algum texto (Ctrl+C) e ele aparece aqui.'));
        box.querySelectorAll('[data-cc]').forEach(b => b.onclick = () => copy(list[+b.dataset.cc], b));
        box.querySelector('#e-clr')?.addEventListener('click', async () => { await fetch('http://127.0.0.1:8766/clip?clear=1'); drawClips(); });
      }
      clearInterval(rot.clipT); rot.clipT = setInterval(() => { if (at('textos')) drawClips(); else clearInterval(rot.clipT); }, 3000);
      draw();
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
          el.innerHTML = empty('Google Agenda não conectado', 'Conecte a sua conta Google em Ajustes → Personalização → Conectores. <button class="e-link" type="button" data-cfg="conn">Abrir</button>');
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
          el.innerHTML = empty('Spotify não conectado', 'Conecte em Ajustes → Personalização → Plugins → Spotify (precisa de Premium). <button class="e-link" type="button" data-cfg="plugins">Abrir</button>');
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
          el.innerHTML = empty('Casa inteligente não conectada', 'Conecte o Home Assistant em Ajustes → Personalização → Plugins → Casa inteligente. <button class="e-link" type="button" data-cfg="plugins">Abrir</button>');
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

  };

  // grupo do menu: abas em cima e a tela da aba escolhida embaixo
  function group(g) {
    const el = $v(g);
    if (!el.dataset.ready) {
      el.dataset.ready = '1';
      el.innerHTML = `<div class="e-tabs" role="tablist">${GROUPS[g].map(([k, l]) => `<button type="button" role="tab" data-sub="${k}">${ICON(I[k])}<span>${l}</span><em></em></button>`).join('')}</div>`
        + GROUPS[g].map(([k]) => `<div class="e-sub" data-v="${k}" hidden></div>`).join('');
      el.querySelectorAll('[data-sub]').forEach(b => b.onclick = () => { tab[g] = b.dataset.sub; group(g); });
    }
    el.querySelectorAll('[data-sub]').forEach(b => b.classList.toggle('on', b.dataset.sub === tab[g]));
    el.querySelectorAll('.e-sub').forEach(x => { x.hidden = x.dataset.v !== tab[g]; });
    root.querySelector('#e-title').textContent = TITLES[g];
    tools.innerHTML = '';
    R[tab[g]]();
    badges();
  }

  function markCfg() {
    const on = document.querySelector('#cfg-back .cfg-nav .tab.active, .cfg-nav .tab.active')?.dataset.tab;
    const el = $v('ajustes');
    el.querySelectorAll('[data-tab]').forEach(b => b.classList.toggle('on', b.dataset.tab === on));
    const gi = el.querySelector(`[data-tab="${on}"]`)?.closest('[data-grpv]')?.dataset.grpv;
    el.querySelectorAll('[data-grpv]').forEach(x => { x.hidden = x.dataset.grpv !== gi; });
    el.querySelectorAll('[data-grp]').forEach(b => b.classList.toggle('on', b.dataset.grp === gi));
    $v('ajustes').querySelector('[data-tab].on')?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }
  // de qualquer lugar ("Nova skill", pedido de configuracao...): abre as configuracoes aqui mesmo, sem a janela
  window.openSettings = async () => { notchExpand(true); show('ajustes'); };
  // botoes "Abrir" das telas: levam direto a secao certa das configuracoes
  root.addEventListener('click', (e) => {
    const b = e.target.closest('[data-cfg]'); if (!b) return;
    showPane(b.dataset.cfg); show('ajustes');
  });

  function renderPcTiles() {
    const el = $v('pc').querySelector('#e-pt'); if (!el) return;
    const v = (id) => $(id)?.textContent || '--';
    el.innerHTML = [['CPU', 'v-cpu'], ['RAM', 'v-ram'], ['GPU', 'v-gpu'], ['TEMP', 'v-temp'], ['REDE', 'v-net']]
      .map(([k, id]) => `<div class="e-tile"><small>${k}</small><b>${esc(v(id))}</b></div>`).join('');
    $v('pc').querySelector('#e-pcc')?.setAttribute('aria-pressed', String($('pc-btn').getAttribute('aria-pressed') === 'true'));
  }

  // ---------- rotina: tarefas, timers e habitos (servidor guarda; aqui conta o tempo e toca o alarme) ----------
  const rot = { data: { timers: [], tasks: [], habits: [] }, skew: 0, fired: new Set() };
  rot.post = (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
    .then(r => r.ok ? r.json() : r.json().then(j => Promise.reject(new Error(j.detail || r.statusText))))
    .catch(e => { try { flash(e.message); } catch {} });
  rot.call = (method, url, body) => fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined }).then(rot.refresh);
  rot.refresh = async () => {
    try { const j = await getJSON('/api/rotina'); rot.skew = j.now - Date.now() / 1000; rot.data = j; } catch { return; }
    drawRotina();
  };
  const nowS = () => Date.now() / 1000 + rot.skew;
  const mmss = (s) => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
    return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(x).padStart(2, '0'); };
  const KIND_ICON = { timer: '⏱', lembrete: '🔔', foco: '🎯', pausa: '☕', cronometro: '⏱' };
  const PRIO_LABEL = { alta: 'Alta', media: 'Média', baixa: 'Baixa' };
  const running = () => rot.data.timers.filter(t => t.stopped == null && !t.fired && (t.ends == null || t.ends > nowS() - 1));

  function timerRow(t, small = false) {
    const left = t.ends ? t.ends - nowS() : nowS() - t.started;
    const pct = t.ends ? Math.max(0, Math.min(100, 100 * left / (t.ends - t.started))) : 0;
    return `<div class="e-item e-timer" data-tid="${esc(t.id)}"><span class="e-tico">${KIND_ICON[t.kind] || '⏱'}</span>
      <div class="e-txt"><b>${esc(t.label)}</b>${t.ends ? `<i class="e-bar"><b style="width:${pct}%"></b></i>` : `<small>${t.stopped ? 'parado' : 'contando'}</small>`}</div>
      <span class="e-tleft">${mmss(left)}</span>
      <button class="e-x" type="button" data-tstop="${esc(t.id)}" title="${t.kind === 'cronometro' ? 'Parar' : 'Cancelar'}">${t.kind === 'cronometro' && !t.stopped ? '■' : '✕'}</button></div>`;
  }
  function drawTimers() {
    const el = $v('timers').querySelector('#e-xl');
    const list = rot.data.timers.filter(t => !t.fired);
    if (el) el.innerHTML = list.length ? list.map(t => timerRow(t)).join('') : empty('Nenhum timer correndo', 'Escolha um tempo acima ou peça: "timer de 10 minutos para a pizza".');
    bindTimerBtns($v('timers'));
  }
  function bindTimerBtns(box) {
    box.querySelectorAll('[data-tstop]').forEach(b => b.onclick = () => rot.call('DELETE', `/api/timers/${b.dataset.tstop}`));
  }
  function drawTasks() {
    const el = $v('tarefas').querySelector('#e-tl'); if (!el) return;
    const all = rot.data.tasks, tops = all.filter(t => !t.parent || !all.some(p => p.id === t.parent));
    const row = (t, sub) => `<div class="e-item e-task${t.done ? ' done' : ''}${sub ? ' sub' : ''}">
        <button class="e-check" type="button" data-done="${esc(t.id)}" aria-pressed="${t.done}" title="Concluir"></button>
        <div class="e-txt"><b>${esc(t.title)}</b>${t.due ? `<small>prazo: ${esc(t.due)}</small>` : ''}</div>
        ${sub ? '' : `<span class="e-prio p-${esc(t.priority)}">${PRIO_LABEL[t.priority] || ''}</span>
        <button class="e-x" type="button" data-sub="${esc(t.id)}" title="Adicionar subtarefa">＋</button>`}
        <button class="e-x" type="button" data-del="${esc(t.id)}" title="Apagar">✕</button></div>`;
    el.innerHTML = tops.length ? tops.map(t => row(t) + all.filter(s => s.parent === t.id).map(s => row(s, true)).join('')).join('')
      : empty('Nada na lista', 'Adicione acima ou peça: "adiciona na lista: comprar café".');
    bindTaskBtns($v('tarefas'));
  }
  function bindTaskBtns(box) {
    box.querySelectorAll('[data-done]').forEach(b => b.onclick = () => rot.call('PATCH', `/api/tasks/${b.dataset.done}`, { done: b.getAttribute('aria-pressed') !== 'true' }));
    box.querySelectorAll('[data-del]').forEach(b => b.onclick = () => rot.call('DELETE', `/api/tasks/${b.dataset.del}`));
    box.querySelectorAll('[data-sub]').forEach(b => b.onclick = async () => {
      const t = prompt('Subtarefa:'); if (t && t.trim()) { await rot.post('/api/tasks', { title: t.trim(), parent: b.dataset.sub }); rot.refresh(); }
    });
  }
  function habitCard(h, mini = false) {
    const pct = Math.min(100, 100 * h.count / h.target), ok = h.count >= h.target;
    return `<div class="e-tile e-habit${ok ? ' ok' : ''}${mini ? ' mini' : ''}"><small>${esc(h.icon || '')} ${esc(h.name)}</small>
      <b>${h.count}<span>/${h.target}${h.unit ? ' ' + esc(h.unit) : ''}</span></b><i class="e-bar"><b style="width:${pct}%"></b></i>
      <div class="e-hbtn">${mini ? '' : `<button class="e-btn e-icon" type="button" data-hlog="${esc(h.id)}" data-d="-1" title="Tirar um">−</button>`}
        <button class="e-btn e-icon acc" type="button" data-hlog="${esc(h.id)}" data-d="1" title="Mais um">+</button>
        ${mini ? '' : `<button class="e-x" type="button" data-hdel="${esc(h.id)}" title="Apagar hábito">✕</button>`}</div></div>`;
  }
  function drawHabits() {
    const el = $v('habitos').querySelector('#e-hg'); if (!el) return;
    el.innerHTML = rot.data.habits.length ? rot.data.habits.map(h => habitCard(h)).join('') : empty('Nenhum hábito', 'Crie um abaixo.');
    bindHabitBtns($v('habitos'));
  }
  function bindHabitBtns(box) {
    box.querySelectorAll('[data-hlog]').forEach(b => b.onclick = () => rot.post(`/api/habits/${b.dataset.hlog}/log`, { delta: +b.dataset.d }).then(rot.refresh));
    box.querySelectorAll('[data-hdel]').forEach(b => b.onclick = () => { if (confirm('Apagar este hábito e o histórico dele?')) rot.call('DELETE', `/api/habits/${b.dataset.hdel}`); });
  }
  // coluna "agora" do Inicio (um cartao so): timers correndo, as 3 primeiras tarefas e os habitos numa linha
  function drawExtra() {
    const el = conv.querySelector('#e-extra');
    const tm = running(), pend = rot.data.tasks.filter(t => !t.done && !t.parent);
    const go = (k, label) => `<button class="e-link" type="button" data-go="${k}">${label}</button>`;
    el.innerHTML = (tm.length ? `<div class="e-ctitle">Timers</div>${tm.map(t => timerRow(t, true)).join('')}` : '')
      + `<div class="e-ctitle">Tarefas ${go('tarefas', pend.length > 3 ? `+${pend.length - 3}` : 'abrir')}</div>`
      + (pend.length ? pend.slice(0, 3).map(t => `<div class="e-item e-task mini"><button class="e-check" type="button" data-done="${esc(t.id)}" aria-pressed="false"></button>
          <div class="e-txt"><b>${esc(t.title)}</b></div>${t.priority === 'alta' ? '<span class="e-prio p-alta">!</span>' : ''}</div>`).join('')
        : `<p class="e-dim e-none">Nada pendente.</p>`)
      + (rot.data.habits.length ? `<div class="e-ctitle">Hoje ${go('habitos', 'abrir')}</div>` + rot.data.habits.slice(0, 3).map(h => `
          <div class="e-hrow${h.count >= h.target ? ' ok' : ''}"><span>${esc(h.icon || '•')} ${esc(h.name)}</span>
            <i class="e-bar"><b style="width:${Math.min(100, 100 * h.count / h.target)}%"></b></i>
            <small>${h.count}/${h.target}</small><button class="e-btn e-icon acc" type="button" data-hlog="${esc(h.id)}" data-d="1" title="Mais um">+</button></div>`).join('') : '');
    bindTimerBtns(el); bindTaskBtns(el); bindHabitBtns(el);
    el.querySelectorAll('[data-go]').forEach(b => b.onclick = () => open(b.dataset.go));
  }
  function badges() {
    const n = { tarefas: rot.data.tasks.filter(t => !t.done && !t.parent).length, timers: running().length,
      habitos: rot.data.habits.filter(h => h.count < h.target).length };
    $v('rotina').querySelectorAll('[data-sub] em').forEach(e => { const k = e.parentElement.dataset.sub; e.textContent = n[k] || ''; });
  }
  function drawRotina() {
    drawExtra(); badges();
    if (at('tarefas')) drawTasks();
    if (at('timers')) drawTimers();
    if (at('habitos')) drawHabits();
  }
  // a cada segundo: contagem na pilula e nas listas; no fim, alarme (so uma tela toca: o servidor marca quem avisou)
  setInterval(() => {
    const tm = running(), now = nowS();
    const next = tm.filter(t => t.ends).sort((a, b) => a.ends - b.ends)[0];
    const sw = tm.find(t => t.kind === 'cronometro' && !t.stopped);
    entAct('timer', next ? `<span class="np-timer">${KIND_ICON[next.kind]} ${esc(next.label)} <b>${mmss(next.ends - now)}</b></span>`
      : sw ? `<span class="np-timer">⏱ <b>${mmss(now - sw.started)}</b></span>` : '', 5);
    document.querySelectorAll('#ent .e-timer').forEach(r => {
      const t = rot.data.timers.find(x => x.id === r.dataset.tid); if (!t) return;
      const left = t.ends ? t.ends - now : (t.stopped || now) - t.started;
      r.querySelector('.e-tleft').textContent = mmss(left);
      const bar = r.querySelector('.e-bar b'); if (bar && t.ends) bar.style.width = Math.max(0, Math.min(100, 100 * left / (t.ends - t.started))) + '%';
    });
    for (const t of rot.data.timers) {
      if (t.ends && !t.fired && t.ends <= now && !rot.fired.has(t.id)) { rot.fired.add(t.id); ring(t); }
    }
  }, 1000);
  async function ring(t) {
    const r = await rot.post(`/api/timers/${t.id}/fire`);
    rot.refresh();
    if (!r || !r.timer) return;                         // outra tela (janela/celular) ja avisou
    const msg = { lembrete: `Lembrete: ${t.label}`, foco: `Fim do foco! Hora de ${r.next ? 'uma pausa de ' + t.then_break + ' minutos' : 'descansar'}.`,
      pausa: 'A pausa acabou. Bora voltar?' }[t.kind] || `Tempo esgotado: ${t.label}.`;
    entAct('alarm', `<span class="np-alarm">⏰ ${esc(msg)}</span>`, 10, 20000);
    try { beep(); setTimeout(beep, 600); setTimeout(beep, 1200); } catch {}
    try { playSpeech(fetchSpeech(msg), { status: false }); } catch {}
    try { flash(msg); } catch {}
  }
  $('notch-pill').addEventListener('click', () => window.entAct?.('alarm', ''), true);   // clicar na pilula cala o aviso
  // lembrete de pausa (opcional, neste aparelho): a cada 50 min
  const breakOn = () => { try { return localStorage.getItem('aura.break') === '1'; } catch { return false; } };
  const setBreak = (on) => { try { localStorage.setItem('aura.break', on ? '1' : '0'); } catch {} };
  setInterval(() => {
    if (!breakOn()) return;
    const msg = 'Hora de uma pausa: levanta, alonga e bebe uma água.';
    entAct('alarm', `<span class="np-alarm">🧘 ${msg}</span>`, 10, 20000);
    try { beep(); playSpeech(fetchSpeech(msg), { status: false }); } catch {}
  }, 50 * 60 * 1000);
  setInterval(rot.refresh, 3000);

  // ---------- entalhe vivo: o que esta tocando, volume e (fase 2) timers na pilula e no Inicio ----------
  // O agente do Windows le a musica de qualquer programa (controles de midia do Windows) e o volume do sistema.
  const act = {};                      // atividades da pilula: chave -> { html, prio, until }
  const pill = $('notch-pill');
  const actEl = E('span', { className: 'np-act', id: 'np-act' });
  pill.insertBefore(actEl, $('np-time'));
  let lastW = 0;
  function drawPill() {
    const now = Date.now();
    const top = Object.entries(act).filter(([, a]) => !a.until || a.until > now).sort((x, y) => y[1].prio - x[1].prio)[0];
    const html = top ? top[1].html : '';
    if (actEl.dataset.html !== html) { actEl.innerHTML = html; actEl.dataset.html = html; }
    actEl.hidden = !html;
    if (!notchMini()) return;
    // largura que cabe tudo: rosto + atividade + relogio + margens
    const vis = [...pill.children].filter(c => !c.hidden);
    const w = Math.ceil(vis.reduce((t, c) => t + c.getBoundingClientRect().width, 0) + 10 * (vis.length - 1) + 30);
    if (Math.abs(w - lastW) > 2) { lastW = w; desk.api?.set_pill(w); }
  }
  window.entAct = (key, html, prio = 1, ms = 0) => {   // html vazio apaga; ms = some sozinho depois desse tempo
    if (!html) delete act[key]; else act[key] = { html, prio, until: ms ? Date.now() + ms : 0 };
    drawPill();
  };
  setInterval(drawPill, 500);

  const media = { cur: null, vol: null, muted: null, artKey: '' };
  const mediaPost = (action, level) => fetch('/api/media', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, level }) }).then(r => r.ok ? r.json() : r.json().then(j => Promise.reject(new Error(j.detail))))
    .catch(e => { try { flash('Mídia: ' + e.message); } catch {} });
  function drawPlayer() {
    const el = conv.querySelector('#e-player'), m = media.cur;
    if (!LOCAL_PAGE) { el.innerHTML = ''; return; }
    const key = m ? m.key + m.playing + media.artKey : 'none';
    if (el.dataset.key !== key) {
      el.dataset.key = key;
      if (!m) {
        el.innerHTML = `<div class="e-np-none">${ICON(I.musica)}<span>Nada tocando</span><button class="e-link" type="button" id="e-pl-go">tocar algo</button></div>`;
        el.querySelector('#e-pl-go').onclick = () => sendText('toca uma música');
      } else {
        el.innerHTML = `<div class="e-player"><div class="e-pl-top">
            <span class="e-art">${m.art ? `<img src="http://127.0.0.1:8766/art?k=${encodeURIComponent(m.key)}" alt="">` : ICON(I.musica)}</span>
            <div class="e-txt"><b title="${esc(m.title)}">${esc(m.title)}</b><small>${esc(m.artist || '')}${m.app ? ' · ' + esc(m.app) : ''}</small></div></div>
          <div class="e-pl-ctl">
            <button class="e-btn e-icon" type="button" data-m="previous" title="Anterior">${ICON(I.prev)}</button>
            <button class="e-btn e-icon acc" type="button" data-m="play_pause" title="${m.playing ? 'Pausar' : 'Tocar'}">${ICON(m.playing ? I.pause : I.play)}</button>
            <button class="e-btn e-icon" type="button" data-m="next" title="Próxima">${ICON(I.next)}</button></div>
          <label class="e-vol">${ICON(I.vol)}<input type="range" min="0" max="100" step="2" id="e-vol"><b id="e-vol-n"></b></label></div>`;
        el.querySelectorAll('[data-m]').forEach(b => b.onclick = () => mediaPost(b.dataset.m).then(pollAgent));
        let t = 0;
        el.querySelector('#e-vol').oninput = (ev) => {
          media.vol = +ev.target.value; el.querySelector('#e-vol-n').textContent = media.vol + '%';
          clearTimeout(t); t = setTimeout(() => mediaPost('set_volume', media.vol), 180);
        };
      }
    }
    const r = el.querySelector('#e-vol');
    if (r && document.activeElement !== r && media.vol != null) { r.value = media.vol; el.querySelector('#e-vol-n').textContent = media.muted ? 'mudo' : media.vol + '%'; }
  }
  async function pollAgent() {
    if (!LOCAL_PAGE) return;
    let j;
    try { j = await fetch(AGENT_METRICS, { cache: 'no-store' }).then(r => r.json()); } catch { return; }
    const m = j.media && j.media.title ? j.media : null;
    media.cur = m; media.artKey = m && m.art ? m.key : '';
    // pilula: musica tocando (equalizador + nome)
    entAct('media', m && m.playing ? `<i class="np-eq"><b></b><b></b><b></b></i><span class="np-song">${esc(m.title)}${m.artist ? ' · ' + esc(m.artist) : ''}</span>` : '', 1);
    // pilula: o volume mudou (por voz, teclado ou aqui): mostra a barra por um instante
    if (j.volume != null && media.vol != null && (j.volume !== media.vol || j.muted !== media.muted)) {
      entAct('volume', `<span class="np-vol">${ICON(j.muted ? I.mute : I.vol)}<i><b style="width:${j.muted ? 0 : j.volume}%"></b></i>${j.muted ? 'mudo' : j.volume + '%'}</span>`, 9, 2500);
    }
    if (document.activeElement?.id !== 'e-vol') { media.vol = j.volume; media.muted = j.muted; }
    drawPlayer();
  }
  setInterval(pollAgent, 1500);
  pollAgent();
  rot.refresh();

  // ---------- arrastar para outro monitor ----------
  // Segure a pilula (ou o rostinho do painel aberto) e arraste: ela segue o mouse e, ao soltar, vai para o topo
  // do monitor onde caiu (e lembra dele). So no app de mesa do Windows.
  let drag = null, dragging = false;
  const realExpand = window.notchExpand;
  window.notchExpand = (pin) => { if (!dragging) realExpand(pin); };       // durante o arraste nao abre
  const grab = (el) => {
    el.addEventListener('pointerdown', (e) => { if (e.button === 0 && desk.api?.drag_start) drag = { x: e.screenX, y: e.screenY }; });
    el.addEventListener('pointermove', (e) => {
      if (!drag || dragging || !(e.buttons & 1) || Math.hypot(e.screenX - drag.x, e.screenY - drag.y) < 6) return;
      dragging = true; drag = null; clearTimeout(notch.hoverT);
      if (!notchMini()) { notch.pinned = false; document.documentElement.classList.add('mini'); }
      desk.api.drag_start().finally(() => setTimeout(() => { dragging = false; }, 500));
    });
    el.addEventListener('pointerup', () => { drag = null; });
  };
  grab(pill); grab(root.querySelector('.e-brand'));
  root.querySelector('.e-brand').title = 'Segure e arraste para levar o entalhe a outro monitor';
  document.addEventListener('click', (e) => { if (dragging && pill.contains(e.target)) { e.stopPropagation(); e.preventDefault(); } }, true);

  // ---------- expressoes do rostinho ----------
  // O rosto muda conforme a conversa (feliz, rindo, surpresa, triste, carinho, brava) e, parado, olha em volta,
  // pisca duplo e cochila depois de um tempo sem ninguem por perto. Com musica tocando, balanca no ritmo.
  let moodT = 0, lastUser = '';
  function mood(m, ms = 4500) {
    clearTimeout(moodT);
    if (m) document.body.dataset.mood = m; else delete document.body.dataset.mood;
    if (m && ms) moodT = setTimeout(() => { delete document.body.dataset.mood; }, ms);
  }
  window.entMood = mood;
  const MOODS = [
    ['bravo', /\b(burra|idiota|lixo|in[uú]til|droga|porra|caralho|merda|maldit\w*)\b/i, 'user'],
    ['carinho', /\b(obrigad[oa]|valeu|te amo|gosto de voc[eê]|voc[eê] [eé] (demais|incr[ií]vel|linda|fofa)|boa garota|parab[eé]ns)\b/i, 'user'],
    ['rindo', /(haha|hehe|kkk|rsrs|😂|🤣|piada)/i, 'bot'],
    ['triste', /\b(n[aã]o consegui|infelizmente|desculp\w*|deu erro|falhou|n[aã]o deu)\b/i, 'bot'],
    ['surpreso', /\b(uau|nossa|caramba|eita|incr[ií]vel|s[eé]rio\?)\b/i, 'bot'],
    ['feliz', /\b(pronto|prontinho|feito|consegui|combinado|anotado|tocando|abri|criei|salvei|copiad[oa]|meta do dia batida)\b|✅/i, 'bot'],
  ];
  function reactTo(reply) {
    const hit = MOODS.find(([, re, who]) => re.test(who === 'user' ? lastUser : reply || ''));
    if (hit) mood(hit[0]);
    lastUser = '';
  }
  const realSend = window.sendText;
  window.sendText = (text, ...rest) => { lastUser = String(text || ''); return realSend(text, ...rest); };
  const realRender = window.render;
  window.render = async (res) => { const r = await realRender(res); reactTo(res && res.reply); return r; };
  const realEntry = window.entry;
  window.entry = (kind, ...rest) => { if (kind === 'err') mood('triste'); return realEntry(kind, ...rest); };
  const realLive = window.onLiveEvent;
  let liveBot = '';
  window.onLiveEvent = (ev) => {
    if (ev.type === 'input') lastUser += ev.text;
    if (ev.type === 'output') liveBot += ev.text;
    if (ev.type === 'turn_complete') { reactTo(liveBot); liveBot = ''; if (cfg.quiet_mode === true) { try { beep(); } catch {} } }
    return realLive(ev);
  };
  // parada: de vez em quando olha para os lados ou pisca duas vezes; depois de 20 min sem nada, cochila
  let lastAct = Date.now();
  ['pointermove', 'keydown', 'pointerdown'].forEach(ev => document.addEventListener(ev, () => {
    lastAct = Date.now(); if (document.body.dataset.mood === 'sono') mood('');
  }, { passive: true }));
  setInterval(() => {
    const busy = ['listening', 'thinking', 'speaking'].includes(document.body.dataset.state);
    if (busy) { lastAct = Date.now(); if (document.body.dataset.mood === 'sono') mood(''); return; }
    document.body.classList.toggle('np-groove', !!(media.cur && media.cur.playing));     // musica: balanca
    if (document.body.dataset.mood) return;
    if (Date.now() - lastAct > 20 * 60 * 1000 && !(media.cur && media.cur.playing)) { mood('sono', 0); return; }
    if (Math.random() < 0.35) {
      const idle = Math.random() < 0.5 ? 'olhar' : 'piscar';
      document.body.dataset.idle = idle; setTimeout(() => { delete document.body.dataset.idle; }, 1800);
    }
  }, 9000);

  show('conversa');
})();
