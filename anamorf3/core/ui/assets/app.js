'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="access-token"]').content;
const state = {session:null,tools:[],task:null,events:[],poll:null,view:'chat',modelReady:false};
const labels = {queued:'Ожидает',running:'Выполняется',done:'Завершена',failed:'Ошибка',cancelled:'Остановлена'};
const toolLabels = {file_read:'Прочитать файл',file_list:'Показать папку',file_search:'Найти текст',file_patch:'Изменить фрагмент',file_create:'Создать файл',command_run:'Запустить команду'};
const paramLabels = {path:'Путь относительно проекта',start:'Первая строка',count:'Количество строк',text:'Текст',sha256:'Хэш исходного файла',old:'Исходный фрагмент',new:'Новый фрагмент',argv:'Программа и аргументы (JSON-массив)',cwd:'Рабочая папка',timeout:'Лимит времени, секунд'};
function fit(){const k=innerHeight/1080;$('stage').style.width=Math.round(innerWidth/k)+'px';$('stage').style.transform='scale('+k+')';}
addEventListener('resize',fit);fit();
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function fail(e){$('error').hidden=false;$('error').textContent=e.message||String(e);}
async function api(path,data){
  const r=await fetch(path,{method:data===undefined?'GET':'POST',headers:{'Authorization':'Bearer '+token,'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});
  const value=await r.json();if(!r.ok)throw new Error(value.error||'Ошибка '+r.status);$('error').hidden=true;return value;
}
function action(fn){return async()=>{try{await fn();}catch(e){fail(e);}};}
function view(name){state.view=name;for(const id of ['projects','chat','plan','history'])$(id+'-panel').hidden=id!==name;
  $('task-detail').hidden=!state.task||!['chat','plan'].includes(name);
  const names={projects:'Проекты',chat:'Диалог',plan:'План действий',history:'Журнал задач'};$('view-title').textContent=names[name];
  for(const [id,tab] of [['up','projects'],['chat','chat'],['hands','plan'],['history','history']])$(id).classList.toggle('act',tab===name);
  if(name==='history')loadTasks().catch(fail);if(name==='projects')loadSessions().catch(fail);
}
function chooseSession(session){state.session=session;localStorage.setItem('anamorf3.session',session.id);$('project-name').textContent=session.root;$('root-path').value=session.root;$('project-title').value=session.title;}
async function loadSessions(){const rows=await api('/api/sessions');$('session-list').replaceChildren();for(const s of rows){const b=el('button',s.title,'list-row');b.append(el('small',s.root));b.onclick=()=>{chooseSession(s);state.task=null;view('chat');};$('session-list').append(b);}return rows;}
async function loadTasks(){if(!state.session)return;const tasks=await api('/api/tasks?session_id='+state.session.id);$('task-list').replaceChildren();for(const t of tasks){const b=el('button',t.input,'list-row');b.append(el('small',labels[t.state]+' · '+new Date(t.created*1000).toLocaleString('ru')));b.onclick=action(async()=>{view('chat');await selectTask(t.id);});$('task-list').append(b);}}
function addStep(name='file_list'){
  const card=el('div',undefined,'step');const head=el('div',undefined,'step-head');head.append(el('span',String($('steps').children.length+1).padStart(2,'0')));
  const select=el('select');select.setAttribute('aria-label','Действие');for(const t of state.tools){const n=t.function.name;const o=el('option',toolLabels[n]||n);o.value=n;select.append(o);}select.value=name;card.append(head);head.append(select);
  const remove=el('button','×');remove.title='Удалить шаг';remove.onclick=()=>card.remove();head.append(remove);const fields=el('div');card.append(fields);
  function draw(){fields.replaceChildren();const schema=state.tools.find(t=>t.function.name===select.value).function.parameters;
    for(const [key,s] of Object.entries(schema.properties)){
      const lab=el('label',paramLabels[key]||key);const input=el(['text','old','new','argv'].includes(key)?'textarea':'input');input.dataset.key=key;input.dataset.type=s.type;
      input.placeholder=(schema.required||[]).includes(key)?'Обязательно':'Необязательно';input.setAttribute('aria-label',paramLabels[key]||key);
      if(s.type==='integer'){input.type='number';input.min=String(s.minimum||1);if(s.maximum)input.max=String(s.maximum);}
      if(key==='path'&&select.value==='file_list')input.value='.';if(key==='argv')input.placeholder='["python", "--version"]';
      lab.append(input);fields.append(lab);
    }
    const tool=state.tools.find(t=>t.function.name===select.value);if(tool.approval)fields.append(el('p','Это действие запросит подтверждение конкретных параметров перед выполнением.','hint'));
  }
  select.onchange=draw;card.dataset.step='1';$('steps').append(card);draw();
}
function readSteps(){return [...$('steps').children].map(card=>{const name=card.querySelector('select').value,args={};for(const input of card.querySelectorAll('[data-key]')){if(input.value==='')continue;const type=input.dataset.type;args[input.dataset.key]=type==='integer'?Number(input.value):type==='array'?JSON.parse(input.value):input.value;}return {name,args};});}
function jsonNode(data){return el('pre',JSON.stringify(data,null,2));}
async function selectTask(id){if(state.poll)clearTimeout(state.poll);state.task=await api('/api/tasks/'+id);state.events=await api('/api/events?task_id='+id);drawTask();if(state.task.state==='running')state.poll=setTimeout(()=>selectTask(id).catch(fail),650);}
function drawTask(){const task=state.task;$('task-detail').hidden=false;$('welcome').hidden=true;$('task-title').textContent=task.input;$('task-state').textContent=labels[task.state];$('task-actions').replaceChildren();$('events').replaceChildren();
  if(task.state==='queued'&&task.detail==='prepared manual plan'){const run=el('button','Выполнить план','action');run.onclick=action(async()=>{await api('/api/tasks/'+task.id+'/run',{});await selectTask(task.id);});$('task-actions').append(run);}
  if(['running','queued'].includes(task.state)){const stop=el('button','Остановить','action');stop.onclick=action(async()=>{await api('/api/tasks/'+task.id+'/cancel',{});await selectTask(task.id);});$('task-actions').append(stop);}
  if(task.state==='queued'&&task.detail==='waiting for approval'){
    const ev=[...state.events].reverse().find(e=>e.type==='task.progress'&&e.data.kind==='approval');
    if(ev){const data=ev.data.data;const box=el('div',undefined,'approval');box.append(el('h3','Разрешить действие?'),el('p',toolLabels[data.tool]||data.tool),jsonNode(data.args));const approve=el('button','Разрешить именно это действие','action');approve.onclick=action(async()=>{await api('/api/tasks/'+task.id+'/approve',{approval_id:data.approval_id});await selectTask(task.id);});box.append(approve);$('events').append(box);}
  }
  for(const ev of state.events){if(!['tool.call','tool.result','task.finished','task.failed','task.cancelled','task.progress'].includes(ev.type)||ev.data.kind==='approval')continue;
    const box=el('article',undefined,'event '+(ev.data.status||''));const title=ev.type==='tool.call'?'Вызов: '+(toolLabels[ev.data.name]||ev.data.name):ev.type==='tool.result'?'Результат: '+(toolLabels[ev.data.name]||ev.data.name):ev.type==='task.progress'?'Ответ модели: '+(ev.data.model||'модель'):ev.type==='task.finished'?'Завершено':ev.type==='task.failed'?'Ошибка':'Остановлено';box.append(el('h3',title));
    if(ev.data.text)box.append(el('div',ev.data.text,'message assistant'));if(ev.data.error||ev.data.reason)box.append(el('p',ev.data.error||ev.data.reason));
    if(ev.data.data?.files){const list=el('div',undefined,'file-results');for(const file of ev.data.data.files){const row=el('div',file.path,'file-row');row.append(el('small',file.dir?'Папка':file.bytes+' байт'));list.append(row);}box.append(list);}
    const more=el('details');more.append(el('summary',ev.type==='tool.result'?'Доказательства и данные':'Параметры'),jsonNode(ev.data));box.append(more);$('events').append(box);
  }
  if(task.detail&&task.state==='failed')$('events').append(el('p',task.detail));
}
async function refresh(){const status=await api('/api/status');$('connection').textContent='Ядро подключено';state.modelReady=!!status.model.ready;$('send').disabled=!state.modelReady;
  $('model-state').textContent=state.modelReady?(status.model.model||'Модель подключена'):'Модель ещё не подключена';$('model-note').textContent=state.modelReady?'Можешь написать задачу или запустить ручной план.':'Ручные планы работают. Подключение облачных и локальных моделей — следующий этап.';
}
$('up').onclick=()=>view('projects');$('chat').onclick=()=>view('chat');$('hands').onclick=()=>view('plan');$('history').onclick=()=>view('history');$('choose-project').onclick=()=>view('projects');$('open-plan').onclick=()=>view('plan');$('tools-button').onclick=()=>view('plan');$('refresh').onclick=action(refresh);
$('gear').onclick=()=>{document.body.classList.toggle('light');localStorage.setItem('anamorf3.light',document.body.classList.contains('light')?'1':'0');};if(localStorage.getItem('anamorf3.light')==='1')document.body.classList.add('light');
$('project-form').onsubmit=async e=>{e.preventDefault();await action(async()=>{chooseSession(await api('/api/sessions',{root:$('root-path').value,title:$('project-title').value}));state.task=null;view('chat');})()};
$('add-step').onclick=()=>addStep();$('prepare').onclick=action(async()=>{if(!state.session)throw new Error('Сначала выбери проект');const task=await api('/api/plans',{session_id:state.session.id,title:$('plan-title').value,steps:readSteps()});await selectTask(task.id);$('task-detail').scrollIntoView({behavior:'smooth',block:'start'});});
$('inspect').onclick=action(async()=>{if(!state.session)throw new Error('Сначала выбери проект');const task=await api('/api/plans',{session_id:state.session.id,title:'Содержимое проекта',steps:[{name:'file_list',args:{path:'.'}}]});await api('/api/tasks/'+task.id+'/run',{});view('chat');await selectTask(task.id);});
$('say').onsubmit=async e=>{e.preventDefault();await action(async()=>{if(!state.session)throw new Error('Выбери проект');const text=$('txt').value.trim();if(!text)return;const task=await api('/api/chat',{session_id:state.session.id,text,mode:$('mode').value});$('txt').value='';$('welcome').hidden=true;$('conversation').append(el('div',text,'message user'));view('chat');await selectTask(task.id);})()};
$('txt').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();if(state.modelReady)$('say').requestSubmit();}};
(async()=>{try{await refresh();state.tools=await api('/api/tools');addStep();const sessions=await loadSessions();const saved=localStorage.getItem('anamorf3.session');chooseSession(sessions.find(s=>s.id===saved)||sessions[0]||await api('/api/sessions',{root:$('root-path').value,title:'Anamorf'}));view('chat');}catch(e){$('connection').textContent='Нет связи с ядром';fail(e);}})();
