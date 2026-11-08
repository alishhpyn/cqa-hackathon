(() => {
  const $ = id => document.getElementById(id);
  const demo = { switchTab, renderDialogsTable, startEvaluationProcess, renderChecklistEditor,
    saveChecklistNewVersion, openNewCriterionModal, renderAppealsList, toggleApiMode, triggerNewBatchEvaluation };
  let live = false, rows = [], lists = [], draft = null, active = null, requestId = 0;
  const statuses = { queued:'В очереди', running:'Оценивается', completed:'Оценён', failed:'Ошибка' };
  const safe = value => escapeHtml(String(value ?? ''));
  const message = error => showToast(error.message);
  const moveLabels = [
    {symbol: '!', label: 'Сильный ответ', tone: 'good'},
    {symbol: '!?', label: 'Можно лучше', tone: 'partial'},
    {symbol: '?', label: 'Ошибка', tone: 'error'},
    {symbol: '??', label: 'Грубое нарушение', tone: 'critical'},
  ];

  function clearMoveAnalysis() {
    $('transcript-feed').querySelectorAll('.move-badge').forEach(badge => badge.remove());
    $('move-analysis').replaceChildren();
    $('move-analysis').hidden = true;
  }

  function showMoveAnalysis(evaluation, transcript) {
    clearMoveAnalysis();
    const turns = new Map(transcript.map((turn, index) => [turn.turn_id ?? index + 1, turn]));
    const marked = new Map();
    for (const criterion of Object.values(evaluation.result?.criteria || {})) {
      const {raw_value: answer, weight, earned_points: points} = criterion;
      if (answer == null || answer === 'N/A') continue;
      const isFlag = /^(Gross Violations|Грубые ошибки)$/i.test(criterion.name?.trim());
      if (isFlag && !['Да', 'YES'].includes(answer)) continue;
      if (!isFlag && !(weight > 0 && Number.isFinite(points))) continue;
      const rank = isFlag ? 3 : points <= 0 ? 2 : points < weight ? 1 : 0;
      for (const id of criterion.evidence_replicas || []) {
        if (turns.get(id)?.speaker !== 'operator') continue;
        const previous = marked.get(id);
        if (!previous || rank > previous.rank) {
          marked.set(id, {rank, criterion});
        }
      }
    }
    const counts = moveLabels.map(() => 0);
    for (const [id, {rank, criterion}] of marked) {
      const turn = $('transcript-turn-'+id);
      if (!turn) continue;
      const {symbol, label, tone} = moveLabels[rank];
      const badge = document.createElement('span');
      badge.className = 'move-badge move-'+tone;
      badge.textContent = symbol;
      badge.title = label + ' · ' + criterion.name + (criterion.explanation ? ' · ' + criterion.explanation : '');
      badge.setAttribute('aria-label', badge.title);
      turn.prepend(badge);
      counts[rank]++;
    }
    const summary = $('move-analysis');
    if (counts.some(Boolean)) {
      summary.innerHTML = `
        <div class="move-analysis-heading">Разбор реплик <span>Оценка ИИ №${safe(evaluation.evaluation_id)}</span></div>
        <ul class="move-legend" aria-label="Отметки реплик оператора">
          ${moveLabels.map(({symbol, label, tone}, i) => `
            <li class="move-chip move-${tone}">
              <span aria-hidden="true">${symbol}</span> ${label} <strong>${counts[i]}</strong>
            </li>`).join('')}
        </ul>`;
    } else {
      summary.textContent = 'В оценке ИИ нет ссылок на реплики оператора для разбора.';
    }
    summary.hidden = false;
  }

  async function api(path, method = 'GET', body) {
    const res = await fetch(window.FreedomAPI.baseUrl.replace(/\/$/, '') + '/api' + path,
      { method, ...(body === undefined ? {} : {headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)}) });
    const data = await res.json();
    if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail ?? data));
    return data;
  }
  $('group-import').addEventListener('submit', async event => {
    event.preventDefault();
    const group_id = $('group-id').value.trim();
    const status = $('import-status');
    const button = event.currentTarget.querySelector('button');
    if (!group_id) return;
    if (!live) {
      status.textContent = 'Включите FastAPI в настройках, чтобы загрузить набор.';
      return;
    }
    button.disabled = true;
    status.textContent = 'Загружаем набор…';
    try {
      await api('/imports', 'POST', {group_id});
      const data = await api('/conversations');
      rows = data.conversations;
      active = null;
      requestId++;
      window.renderDialogsTable();
      status.textContent = 'Набор загружен. Откройте диалог из списка.';
    } catch (error) {
      status.textContent = 'Не удалось загрузить набор. ' + error.message;
    } finally { button.disabled = false; }
  });
  const renderDemoCriteria = renderCriteriaList;
  window.renderCriteriaList = criteria => {
    renderDemoCriteria(criteria);
    for (const card of [...$('criteria-container').children]) {
      const header = card.firstElementChild;
      if (!header?.querySelector('h5')) continue;
      const details = document.createElement('details');
      const summary = document.createElement('summary');
      summary.className = 'cursor-pointer';
      header.classList.add('inline-flex', 'w-[95%]');
      summary.append(header);
      details.append(summary, ...card.childNodes);
      card.append(details);
    }
  };
  function selectLists() {
    const select = $('select-checklist-ver');
    select.replaceChildren(...lists.map(c => new Option(c.name, c.id)));
    if (!lists.length) select.add(new Option('Создайте чек-лист', ''));
  }
  async function loadLists() { lists = await api('/checklists'); selectLists(); }
  window.toggleApiMode = async mode => {
    if (mode === 'live') window.FreedomAPI.setBaseUrl($('api-base-url-input').value.trim());
    demo.toggleApiMode(mode);
    live = mode === 'live';
    requestId++;
    active = null;
    const ticket = requestId;
    const status = $('api-connection-status');
    status.textContent = '';
    $('api-retry').hidden = true;
    if (!live) {
      currentActiveDialog = mockDialogsData[0];
      $('select-checklist-ver').replaceChildren(new Option('Демо', '1'));
      demo.switchTab('dialog-card');
      return;
    }
    rows = [];
    window.switchTab('dialogs');
    status.textContent = 'Сервер запускается. Первый вход может занять около минуты.';
    try {
      const deadline = Date.now() + 90000;
      while (true) {
        try {
          const res = await fetch(window.FreedomAPI.baseUrl.replace(/\/$/, '') + '/api/health',
            {cache:'no-store', signal:AbortSignal.timeout(12000)});
          if (!res.ok || (await res.json()).status !== 'OK') throw new Error('API is not ready');
          break;
        } catch (error) {
          if (ticket !== requestId) return;
          if (Date.now() >= deadline) throw error;
          await new Promise(resolve => setTimeout(resolve, 2500));
        }
        if (ticket !== requestId) return;
      }
      if (ticket !== requestId) return;
      const [data, checklists] = await Promise.all([api('/conversations'), api('/checklists')]);
      if (ticket !== requestId) return;
      rows = data.conversations;
      lists = checklists;
      selectLists();
      window.renderDialogsTable();
      status.textContent = '';
    } catch (e) {
      if (ticket !== requestId) return;
      status.textContent = 'Не удалось загрузить данные. Проверьте подключение и повторите попытку.';
      $('api-retry').hidden = false;
    }
  };
  window.switchTab = tab => {
    if (live && tab === 'dialog-card') {
      if (!active) { demo.switchTab('dialogs'); return showToast('Откройте диалог из списка.'); }
      const current = currentActiveDialog;
      currentActiveDialog = null;
      demo.switchTab(tab);
      currentActiveDialog = current;
      loadCardResult(active.conversation_id, ++requestId);
      return;
    }
    demo.switchTab(tab);
  };
  window.renderDialogsTable = () => {
    if (!live) return demo.renderDialogsTable();
    const body = $('dialogs-table-body');
    body.replaceChildren();
    for (const r of rows) {
      const channel = /voice|call/i.test(r.channel) ? 'Звонок' : 'Чат';
      const lang = $('filter-lang').value, ch = $('filter-channel').value;
      const status = statuses[r.evaluation?.status] || 'Не оценён';
      const selectedStatus = $('filter-status').value;
      const filterStatus = selectedStatus === 'Готово' ? statuses.completed : selectedStatus;
      if (!r.conversation_id.toLowerCase().includes($('filter-search').value.toLowerCase()) ||
          lang !== 'ALL' && lang !== r.language ||
          ch !== 'ALL' && ![channel, r.channel, channel === 'Чат' ? 'Chat' : 'Voice'].includes(ch) ||
          filterStatus !== 'ALL' && filterStatus !== status) continue;
      const tr = body.insertRow();
      tr.className = 'border-b border-surface-border hover:bg-brand-50 cursor-pointer text-xs';
      const displayStatus = r.evaluation?.reviewed ? 'Проверено вручную' : status;
      for (const v of [r.conversation_id,r.language,channel,'—',displayStatus,r.evaluation?.score ?? '—']) {
        const td = tr.insertCell(); td.className = 'p-3'; td.textContent = v;
      }
      const btn = document.createElement('button');
      btn.className = 'p-2 text-brand-700 font-bold';
      btn.textContent = 'Открыть';
      tr.insertCell().append(btn);
      tr.onclick = () => openLive(r.conversation_id).catch(message);
    }
    if (!body.rows.length) body.innerHTML = '<tr><td colspan="7" class="p-6 text-center">Диалоги не найдены</td></tr>';
  };
  window.triggerNewBatchEvaluation = () => live ? showToast('Откройте диалог и нажмите «Оценить диалог».') : demo.triggerNewBatchEvaluation();
  async function openLive(id) {
    const ticket = ++requestId;
    const r = await api('/conversations/'+encodeURIComponent(id));
    if (!live || ticket !== requestId) return;
    active = r;
    clearMoveAnalysis();
    const saved = rows.find(x => x.conversation_id === id)?.evaluation;
    if (saved) active.evaluation = saved;
    currentActiveDialog = {id:r.conversation_id,langTitle:safe(r.language), channelTitle:safe(r.channel),
      status:statuses[saved?.status] || 'Не оценён', hasAudio:false, turns:r.transcript.map((t,i)=>({
        turn_id:Number(t.turn_id ?? i+1),role:t.speaker,author:'',time:safe(t.timestamp),text:t.text
      }))};
    demo.switchTab('dialog-card');
    renderDialogCardView(currentActiveDialog);
    if (r.audio_url && /^https?:\/\//i.test(r.audio_url)) {
      const link = document.createElement('a');
      link.href=r.audio_url; link.target='_blank'; link.rel='noopener noreferrer';
      link.className='block p-2 text-brand-700'; link.textContent='Открыть запись звонка';
      $('transcript-feed').prepend(link);
    }
    $('critical-flaw-box').classList.add('hidden');
    $('score-evaluation-timestamp').textContent='';
    await loadCardResult(id, ticket);
  }
  async function loadCardResult(id, ticket) {
    const current = () => live && ticket === requestId && active?.conversation_id === id;
    const container = $('criteria-container');
    container.textContent = 'Загружаем результаты оценки…';
    try {
      const {results} = await api('/results/'+encodeURIComponent(id));
      if (!current()) return;
      const saved = rows.find(row => row.conversation_id === id)?.evaluation;
      const scored = results.filter(item => item.score != null || item.details?.length);
      const selected = scored.find(item => item.evaluation_id === saved?.evaluation_id)
        ?? scored.find(item => item.details?.some(criterion => criterion.review))
        ?? scored[0];
      if (!selected) {
        container.textContent = 'У диалога пока нет завершённой оценки.';
        return;
      }
      // History contains the reviewed score and criterion answers. The AI payload
      // is supplemental and may be unavailable for older evaluations.
      renderResult(selected, selected.details ?? []);
      try {
        const evaluation = await api('/evaluations/'+selected.evaluation_id);
        if (current()) renderResult({...evaluation, ...selected}, selected.details ?? []);
      } catch {
        // The saved result remains visible even if AI evidence cannot be loaded.
      }
    } catch (error) {
      if (!current()) return;
      if (error.message === 'No evaluation results found') {
        container.textContent = 'У диалога пока нет завершённой оценки.';
      } else {
        container.textContent = 'Не удалось загрузить результаты оценки. Откройте карточку ещё раз.';
        message(error);
      }
    }
  }
  async function showResult(e) {
    const id = active.conversation_id;
    const hist = await api('/results/'+encodeURIComponent(id));
    if (!live || active?.conversation_id !== id || e.conversation_id !== id) return;
    const stored = hist.results.find(x=>x.evaluation_id===e.evaluation_id)?.details || [];
    renderResult(e, stored);
  }
  function renderResult(e, stored) {
    const id = e.conversation_id;
    const raw = Object.values(e.result?.criteria || {});
    $('score-number').textContent=e.score ?? '—';
    $('score-bar').style.width=(e.score ?? 0)+'%';
    const effective = rows.find(row => row.conversation_id === id)?.evaluation;
    $('card-status-badge').textContent =
      (effective?.reviewed && effective.evaluation_id === e.evaluation_id) || stored.some(criterion => criterion.review)
        ? 'Проверено вручную' : statuses.completed;
    $('score-evaluation-timestamp').textContent='Оценка №'+e.evaluation_id;
    $('critical-flaw-box').className='rounded-xl p-2 text-xs font-bold '+(e.gross_violation?'bg-red-100 text-red-800':'bg-emerald-50 text-emerald-800');
    $('critical-flaw-box').textContent=e.gross_violation?'Обнаружено грубое нарушение':'Грубых нарушений нет';
    $('criteria-container').innerHTML=stored.map((c,i)=>{
      const original = raw.find(x=>x.criterion_id===c.criterion_id);
      const a = original || raw[i];
      const canonical = v => ({YES:"Да", NO:"Нет"}[v] ?? String(v));
      const matches = a && canonical(a.raw_value) === canonical(c.answer);
      const evidence=(a?.evidence_replicas || []).filter(Number.isInteger);
      const review = c.review;
      const reviewNote = review ? `<div class="rounded-lg bg-brand-50 p-3 text-sm space-y-1">
        <strong>Проверено аудитором</strong>
        ${a?.raw_value != null ? `<p>Ответ ИИ: ${safe(canonical(a.raw_value))}</p>` : ''}
        <p>Решение аудитора: ${safe(canonical(review.answer))}</p>
        <p>Причина: ${safe(review.reason)}</p>
      </div>` : '';
      return `<details class="p-4 rounded-xl border bg-white space-y-2">
        <summary class="cursor-pointer text-sm"><strong>${safe(c.criterion)}</strong> <span class="font-mono text-xs">${c.answer === "N/A" ? "N/A" : Number(c.weight) === 0 ? safe(c.answer) : safe(c.points)+" из "+safe(c.weight)}</span>${review ? ' <span class="text-xs text-brand-700">Проверено аудитором</span>' : ''}</summary>
        ${reviewNote}
        <p class="text-xs text-charcoal-600">${matches?safe(a.explanation):a?'Исходное объяснение ИИ: '+safe(a.explanation):''}</p>
        <div class="flex gap-2 flex-wrap">${evidence.map(n=>`<button class="text-xs rounded bg-brand-50 px-2 py-1" onclick="highlightAndScrollToTurn(${n})">Реплика №${n}</button>`).join('')}
        <button class="text-xs text-brand-700" onclick="submitLiveAppeal(${Number(e.evaluation_id)},${Number(c.criterion_result_id)})">Оспорить</button></div></details>`;
    }).join('');
  }
  window.startEvaluationProcess = async () => {
    if (!live) return demo.startEvaluationProcess();
    const id = active?.conversation_id, checklist_id=Number($('select-checklist-ver').value);
    if (!id || !checklist_id) return showToast('Выберите диалог и чек-лист.');
    if ($('btn-evaluate').disabled) return;
    const btn=$('btn-evaluate'), timer=$('eval-timer');
    btn.disabled=true;
    clearMoveAnalysis();
    $('eval-error-alert').classList.add('hidden');
    $('eval-loading-alert').classList.remove('hidden');
    timer.textContent='В очереди';
    try {
      const job=await api('/evaluations','POST',{conversation_id:id,checklist_id,checklist_version:'1'});
      const updateRow = evaluation => {
        const row = rows.find(x => x.conversation_id === id);
        if (live && row && !row.evaluation?.reviewed &&
            (row.evaluation?.evaluation_id ?? 0) <= evaluation.evaluation_id) {
          row.evaluation = evaluation;
          window.renderDialogsTable();
        }
      };
      updateRow(job);
      for (let i=0;i<240;i++) {
        await new Promise(resolve=>setTimeout(resolve,2200));
        const e=await api('/evaluations/'+job.evaluation_id);
        if (!live) return;
        updateRow(e);
        timer.textContent=statuses[e.status] || e.status;
        if(e.status==='failed') throw new Error(e.error || 'Оценка завершилась ошибкой');
        if(e.status==='completed') {
          if (active?.conversation_id === id) showMoveAnalysis(e, active.transcript);
          const {conversations} = await api('/conversations');
          if (!live) return;
          rows = conversations;
          window.renderDialogsTable();
          const effective = rows.find(row => row.conversation_id === id)?.evaluation;
          if (active?.conversation_id === id && effective) {
            const result = effective.evaluation_id === e.evaluation_id
              ? e : await api('/evaluations/'+effective.evaluation_id);
            if (active?.conversation_id === id) await showResult(result);
          }
          if (effective?.reviewed && effective.evaluation_id !== e.evaluation_id) {
            showToast(`Новая оценка ИИ: ${e.score ?? '—'}. В списке действует ручная оценка: ${effective.score ?? '—'}.`);
          }
          return;
        }
      }
      throw new Error('Оценка ещё выполняется. Откройте диалог позже.');
    } catch(e) {
      $('eval-error-message').textContent=e.message;
      $('eval-error-alert').classList.remove('hidden');
    } finally { btn.disabled=false; $('eval-loading-alert').classList.add('hidden'); }
  };
  window.submitLiveAppeal = async (evaluation_id,criterion_result_id) => {
    const comment=prompt('Почему вы оспариваете оценку?')?.trim();
    if (!comment) return;
    try { await api('/appeals','POST',{evaluation_id,criterion_result_id,comment}); showToast('Апелляция отправлена.'); }
    catch(e) { message(e); }
  };
  window.renderAppealsList = async () => {
    if(!live) return demo.renderAppealsList();
    try {
      const {appeals}=await api('/appeals');
      if (!live) return;

      const pendingCount = appeals.filter(
        x => x.status === 'pending'
      ).length;

      $('appeals-counter').textContent = pendingCount;
      $('appeals-pending-count').textContent =
        `${pendingCount} на рассмотрении`;
      $('appeals-list-container').innerHTML=appeals.map(x=>`<article class="bg-white border rounded-xl p-4 space-y-2">
        <strong>${safe(x.criterion)}</strong> · ${safe(x.status)}
        <p class="text-sm">${safe(x.comment)}</p><p class="text-xs">Ответ: ${safe(x.original_answer)}</p>
        ${x.status==='pending'?`<button class="bg-brand-50 p-2 rounded" onclick="reviewLive(${Number(x.id)})">Рассмотреть</button>`:`<p class="text-xs">Решение: ${safe(x.reviewer_answer)} · ${safe(x.reviewer_reason)}</p>`}</article>`).join('') || 'Апелляций пока нет.';
    } catch(e) { message(e); }
  };
  window.reviewLive = async id => {
    const value=prompt('Введите итоговый ответ: YES, NO, N/A или число')?.trim();
    if (!value) return;
    const reason=prompt('Причина решения')?.trim();
    if (!reason) return;
    try {
      const r=await api('/appeals/'+id+'/review','POST',{reviewer_answer:Number.isFinite(Number(value))?Number(value):value,reviewer_reason:reason});
      showToast('Пересчитанный итог: '+(r.new_score ?? '—'));
      window.renderAppealsList();
      const {conversations} = await api('/conversations');
      if (!live) return;
      rows = conversations;
      window.renderDialogsTable();
    } catch(e) { message(e); }
  };
  $('api-retry').onclick = () => window.toggleApiMode('live');
  window.addEventListener('DOMContentLoaded', () => {
    if (!window.FREEDOM_API_URL) return;
    $('api-base-url-input').value = window.FREEDOM_API_URL;
    document.querySelector('input[name="api-mode-radio"][value="live"]').checked = true;
    window.toggleApiMode('live');
  });
  window.saveApiSettings = () => {
    toggleApiModal();
    const mode = document.querySelector('input[name="api-mode-radio"]:checked').value;
    window.toggleApiMode(mode);
  };
  const field='w-full border rounded p-2 text-xs';
  window.renderChecklistEditor = () => {
    if(!live) return demo.renderChecklistEditor();
    const editor=$('checklist-editor-list');
    editor.innerHTML=`<div class="p-4 space-y-3"><select id="live-checklist" class="${field}">
    <option value="">Новый чек-лист</option>${lists.map(c=>`<option value="${Number(c.id)}">${safe(c.name)}</option>`).join('')}</select>
    <input id="live-checklist-name" class="${field}" placeholder="Название чек-листа">
    <div id="live-criteria" class="space-y-3"></div></div>`;
    $('live-checklist').onchange=()=>{draft=lists.find(c=>String(c.id)===$('live-checklist').value) || null; fillEditor();};
    $('live-checklist').value=draft?.id ?? '';
    fillEditor();
  };
  function addCriterion(c={}) {
    const el=document.createElement('div');
    el.className='grid gap-2 p-3 bg-brand-50 rounded-xl';
    el.innerHTML=`<input class="${field}" placeholder="Название критерия"><textarea class="${field}" placeholder="Правило"></textarea>
    <select class="${field}"><option value="yes_no">Да / Нет</option><option value="yes_no_na">Да / Нет / N/A</option><option value="numeric">Шкала</option></select>
    <input class="${field}" type="number" min="0" max="100" placeholder="Вес">
    <input class="${field}" placeholder="Шкала через запятую"><label class="text-xs"><input type="checkbox"> Разрешить N/A</label>
    <button class="text-xs text-red-700" type="button">Удалить</button>`;
    const [name,description,type,weight,scale,na]=el.querySelectorAll('input,textarea,select');
    name.value=c.name??''; description.value=c.description??''; type.value=c.answer_type??'yes_no';
    weight.value=c.weight??0; scale.value=c.scale?.join(', ')??''; na.checked=!!c.na_allowed;
    el.querySelector('button').onclick=()=>el.remove();
    $('live-criteria').append(el);
  }
  function fillEditor() {
    $('live-checklist-name').value=draft?.name??'';
    $('live-criteria').replaceChildren();
    (draft?.criteria ?? []).forEach(addCriterion);
  }
  window.openNewCriterionModal = () => live ? addCriterion() : demo.openNewCriterionModal();
  window.saveChecklistNewVersion = async () => {
    if(!live) return demo.saveChecklistNewVersion();
    const name=$('live-checklist-name').value.trim();
    const criteria=[...$('live-criteria').children].map(row=>{
      const [n,d,t,w,s,na]=row.querySelectorAll('input,textarea,select');
      return {name:n.value.trim(),description:d.value.trim(),answer_type:t.value,weight:Number(w.value),
        na_allowed:t.value==='yes_no_na'||t.value==='numeric'&&na.checked,
        scale:t.value==='numeric'?s.value.split(',').map(x=>x.trim()).filter(Boolean).map(Number):null};
    });
    if(!name||!criteria.length||criteria.some(c=>!c.name||!c.description||c.weight<0||c.weight>100||c.scale&&(!c.scale.length||c.scale.some(x=>!Number.isFinite(x))||Math.max(...c.scale)<=0))) {
      return showToast('Заполните название, правила, веса и шкалы.');
    }
    try {
      draft=await api('/checklists','POST',{name:draft&&name===draft.name?name+' · новая версия':name,channel:draft?.channel??'both',language:draft?.language??'ALL',criteria});
      await loadLists(); window.renderChecklistEditor(); showToast('Сохранён новый чек-лист №'+draft.id);
    } catch(e) { message(e); }
  };
})();
