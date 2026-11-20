// Радар навколо LinkedIn: сторінка «Коментарі» і «Хто реагує».
// Сторінка лише показує дані й ставить стан. У LinkedIn вона нічого не робить, публікує людина.
// Дані пише scripts/publish_page.py через wrangler, відкритої адреси для запису немає.

const SKIP = new Set(['not_fit', 'late', 'no_angle', 'other']);

const b64u = s => Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0));
const parts = t => new TextDecoder().decode(b64u(t));

// Перевірка токена Cloudflare Access. Немає токена або він чужий = доступу немає.
export async function verifyAccess(token, env, fetcher = fetch, now = Date.now()) {
  if (!token) return null;
  try {
    const [h, p, sig] = token.split('.');
    const head = JSON.parse(parts(h)), claims = JSON.parse(parts(p));
    if (head.alg !== 'RS256') return null;
    if (claims.iss !== `https://${env.ACCESS_TEAM_DOMAIN}`) return null;
    const aud = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
    if (!aud.includes(env.ACCESS_AUD)) return null;
    if (!claims.exp || claims.exp * 1000 < now) return null;
    const r = await fetcher(`https://${env.ACCESS_TEAM_DOMAIN}/cdn-cgi/access/certs`);
    const jwk = ((await r.json()).keys || []).find(k => k.kid === head.kid);
    if (!jwk) return null;
    const key = await crypto.subtle.importKey('jwk', jwk, { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }, false, ['verify']);
    const ok = await crypto.subtle.verify('RSASSA-PKCS1-v1_5', key, b64u(sig), new TextEncoder().encode(`${h}.${p}`));
    return ok ? (claims.email || 'невідомо') : null;
  } catch { return null; }
}

const json = (o, status = 200) => new Response(JSON.stringify(o), { status, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' } });

async function data(env, url) {
  const days = Math.min(Math.max(Number(url.searchParams.get('days')) || 14, 1), 90);
  const since = new Date(Date.now() - days * 864e5).toISOString().slice(0, 10);
  const [runs, drafts, people] = await env.DB.batch([
    env.DB.prepare('SELECT * FROM comment_run WHERE day >= ? ORDER BY day DESC').bind(since),
    env.DB.prepare('SELECT * FROM comment_draft WHERE day >= ? ORDER BY day DESC, id').bind(since),
    env.DB.prepare('SELECT * FROM engager ORDER BY (grp = \'clients\') DESC, (3 * comments + reactions) DESC LIMIT 800'),
  ]);
  return json({ days, runs: runs.results, drafts: drafts.results, people: people.results });
}

async function setState(request, env, email) {
  // Заголовок JSON не поставить із чужого сайту простим посиланням чи формою.
  if (!(request.headers.get('Content-Type') || '').includes('application/json')) return json({ error: 'очікую JSON' }, 415);
  let b;
  try { b = await request.json(); } catch { return json({ error: 'очікую JSON' }, 400); }
  const id = Number(b.id);
  if (!Number.isInteger(id) || id <= 0) return json({ error: 'немає id' }, 400);
  const at = new Date().toISOString();
  let st;
  if (b.action === 'posted') st = env.DB.prepare("UPDATE comment_draft SET state='posted', final_comment=?, skip_reason=NULL, state_by=?, state_at=? WHERE id=?").bind(String(b.comment || '').slice(0, 3000) || null, email, at, id);
  else if (b.action === 'skipped') st = env.DB.prepare("UPDATE comment_draft SET state='skipped', skip_reason=?, final_comment=NULL, state_by=?, state_at=? WHERE id=?").bind(SKIP.has(b.reason) ? b.reason : 'other', email, at, id);
  else if (b.action === 'undo') st = env.DB.prepare("UPDATE comment_draft SET state='new', skip_reason=NULL, final_comment=NULL, state_by=NULL, state_at=NULL WHERE id=?").bind(id);
  else return json({ error: 'невідома дія' }, 400);
  const r = await st.run();
  if (!r.meta.changes) return json({ error: 'підказку не знайдено' }, 404);
  return json({ ok: true });
}

export default {
  async fetch(request, env) {
    // DEV_EMAIL живе лише в .dev.vars для wrangler dev і не потрапляє в деплой.
    const email = env.DEV_EMAIL || await verifyAccess(request.headers.get('Cf-Access-Jwt-Assertion'), env);
    if (!email) return new Response('Немає доступу. Увійдіть через Cloudflare Access.', { status: 403 });
    const url = new URL(request.url);
    try {
      if (url.pathname === '/api/data' && request.method === 'GET') return await data(env, url);
      if (url.pathname === '/api/state' && request.method === 'POST') return await setState(request, env, email);
    } catch (e) { return json({ error: String(e.message || e) }, 502); }
    if (url.pathname !== '/') return new Response('Не знайдено', { status: 404 });
    return new Response(PAGE, { headers: {
      'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex', 'X-Content-Type-Options': 'nosniff',
      'X-Frame-Options': 'DENY', 'Referrer-Policy': 'same-origin',
      'Content-Security-Policy': "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src 'self'; base-uri 'none'; form-action 'none'",
    } });
  },
};

const PAGE = String.raw`<!doctype html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Радар LinkedIn</title><meta name="robots" content="noindex">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet">
<style>
:root{--ink:#0A0E1A;--blue:#1B6CF2;--blue2:#1459CC;--tint:#E8F0FE;--gold:#F5A623;--body:#3D4352;--dim:#6B7280;--line:#E5E7EB;--card:#F7F8FA;--ok:#E7F6EC;--okt:#17663A}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}body{margin:0;background:#fff;color:var(--body);font:15px/1.5 Manrope,system-ui,sans-serif;overflow-x:hidden}
.wrap{max-width:1040px;margin:0 auto;padding:18px 16px 60px}h1{margin:0;font-size:22px;font-weight:800;color:var(--ink);line-height:1.2}
.top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin:14px 0}.tab{appearance:none;background:none;border:0;border-bottom:3px solid transparent;padding:9px 12px;font:600 15px Manrope,sans-serif;color:var(--dim);cursor:pointer;min-height:44px}.tab.on{color:var(--ink);border-color:var(--blue)}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.kpi{background:var(--card);border-radius:12px;padding:12px 14px;min-width:0}.kpi b{display:block;font-size:30px;font-weight:800;color:var(--ink);line-height:1.1}.kpi.hot b{color:var(--blue)}.kpi span{font-size:13px;color:var(--dim)}
.i{display:inline-grid;place-items:center;width:18px;height:18px;border-radius:50%;border:1px solid var(--line);font:600 11px Manrope;color:var(--dim);cursor:help;margin-left:4px;background:#fff;padding:0;position:relative}.i:hover::after,.i:focus::after{content:attr(data-t);position:absolute;z-index:5;top:22px;left:50%;transform:translateX(-50%);width:min(260px,70vw);background:var(--ink);color:#fff;padding:8px 10px;border-radius:8px;font:500 12.5px/1.45 Manrope;text-align:left}
.line{margin:10px 0 0;font-size:13.5px;color:var(--dim)}.warn{background:#FFF6E5;color:#7A4B00;border-radius:10px;padding:10px 12px;margin:12px 0 0;font-size:14px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}.chips button{appearance:none;border:1px solid var(--line);background:#fff;border-radius:999px;padding:6px 12px;font:600 13px Manrope;color:var(--body);cursor:pointer;min-height:36px}.chips button.on{background:var(--ink);border-color:var(--ink);color:#fff}.chips span{margin-left:5px;font-family:'JetBrains Mono',monospace;font-size:12px;opacity:.75}
.card{border:1px solid var(--line);border-radius:14px;margin-top:12px;overflow:hidden}.post{padding:14px}.who{display:flex;gap:10px}.av{width:42px;height:42px;flex:none;border-radius:50%;background:var(--tint);color:var(--blue2);display:grid;place-items:center;font-weight:800}.who>div{min-width:0}.who b a{color:var(--ink);text-decoration:none}.hl,.t{font-size:13px;color:var(--dim);overflow-wrap:anywhere}.pill{display:inline-block;border-radius:999px;background:var(--card);padding:1px 8px;font-size:12px;font-weight:600;margin-left:4px}.pill.ok{background:var(--ok);color:var(--okt)}
.x{margin:10px 0 0;white-space:pre-wrap;overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}.x.open{display:block}.more{appearance:none;border:0;background:none;color:var(--blue);font:600 13px Manrope;padding:4px 0;cursor:pointer}
.me{background:var(--card);padding:12px 14px;border-top:1px solid var(--line)}textarea{width:100%;margin-top:6px;font:inherit;padding:9px 12px;border:1px solid var(--line);border-radius:10px;background:#fff;color:var(--ink);resize:vertical}
.acts{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;align-items:center}.btn{appearance:none;border:1px solid var(--line);background:#fff;border-radius:10px;padding:8px 12px;font:600 13.5px Manrope;color:var(--ink);cursor:pointer;min-height:40px}.btn.p{background:var(--blue);border-color:var(--blue);color:#fff}.btn.p:hover{background:var(--blue2)}select{font:500 13.5px Manrope;padding:8px;border:1px solid var(--line);border-radius:10px;background:#fff;min-height:40px;max-width:100%}.msg{font-size:13px;color:var(--dim)}
.tw{overflow-x:auto;margin-top:12px;border:1px solid var(--line);border-radius:12px}table{border-collapse:collapse;width:100%;font-size:13.5px;min-width:680px}th{text-align:left;font-weight:600;color:var(--dim);background:var(--card);padding:8px 10px;white-space:nowrap}td{padding:8px 10px;border-top:1px solid var(--line);vertical-align:top}td a{color:var(--ink);font-weight:600}td small{color:var(--dim);display:block}.alert td{background:#FFF6E5}
h2{font-size:15px;font-weight:700;color:var(--ink);margin:22px 0 0}.empty{padding:30px 16px;text-align:center;color:var(--dim);background:var(--card);border-radius:12px;margin-top:12px}
@media(max-width:640px){.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.kpi b{font-size:26px}}
</style></head><body><div class="wrap"><div class="top"><h1>Радар LinkedIn</h1><div class="chips" id="days" style="margin:0"></div></div><div class="tabs"><button class="tab on" data-tab="c">Коментарі</button><button class="tab" data-tab="r">Хто реагує</button></div><div id="pane"><div class="empty">Завантаження…</div></div></div>
<script>
const G={clients:'Клієнти й ліди',engagers:'Приходили під ваші дописи',warm:'Теплі',watchlist:'Свій список',icp:'Покупці',peers:'Колеги по ринку',copilots:'Суміжні',tl:'Лідери думок',signals:'Компанії із сигналом',contacts:'Ваші контакти',topics:'Нові за темами'};
const SK={not_fit:'не наш автор',late:'допис застарів',no_angle:'нема що сказати',other:'інше'};
let S={tab:'c',days:14,state:'new',group:'',rgroup:'',d:null,err:''};
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const li=u=>/^https:\/\/([a-z]+\.)?linkedin\.com\//.test(u||'')?u:'';
const a=(u,t)=>li(u)?'<a href="'+esc(u)+'" target="_blank" rel="noopener">'+esc(t)+'</a>':esc(t);
const inf=t=>'<button class="i" type="button" aria-label="'+esc(t)+'" data-t="'+esc(t)+'">i</button>';
const kpi=(n,l,t,c)=>'<div class="kpi '+(c||'')+'"><b>'+n+'</b><span>'+l+'</span>'+inf(t)+'</div>';
const dt=d=>{if(!d)return'';const p=String(d).slice(0,10).split('-');return p[2]+'.'+p[1]};
const age=m=>m==null?'':m<60?m+' хв':Math.round(m/6)/10+' год';
async function load(){S.err='';try{const r=await fetch('/api/data?days='+S.days);const j=await r.json();if(!r.ok)throw Error(j.error||r.status);S.d=j}catch(e){S.err=e.message}draw()}
function draw(){
  document.getElementById('days').innerHTML=[1,7,14,30].map(x=>'<button data-days="'+x+'" class="'+(S.days===x?'on':'')+'">'+(x===1?'сьогодні':x+' днів')+'</button>').join('');
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('on',t.dataset.tab===S.tab));
  const p=document.getElementById('pane');
  if(S.err){p.innerHTML='<div class="warn">Дані не завантажились: '+esc(S.err)+'</div>';return}
  if(!S.d)return;
  p.innerHTML=S.tab==='c'?comments():people();
}
function comments(){
  const ds=S.d.drafts,t={new:0,posted:0,skipped:0,edited:0};
  for(const x of ds){t[x.state]=(t[x.state]||0)+1;if(x.state==='posted'&&x.final_comment&&x.final_comment.trim()!==(x.comment||'').trim())t.edited++}
  const today=new Date().toISOString().slice(0,10),run=S.d.runs[0];
  const stale=!run||(Date.now()-new Date(run.day))/864e5>3;
  let h='<div class="kpis">'+kpi(t.new,'чекають на вас','Підказки, з якими ви ще нічого не зробили. Свіжі зверху: допис старший за добу працює гірше.','hot')
   +kpi(ds.filter(x=>x.state==='posted'&&(x.state_at||'').slice(0,10)===today).length,'опубліковано сьогодні','Скільки коментарів ви позначили сьогодні. Орієнтир 5–15 на день.')
   +kpi(t.skipped,'пропущено','Причина пропуску показує, де радар бере не тих авторів або пише слабко.')
   +kpi(t.posted?Math.round(t.edited/t.posted*100)+'%':'—','правили текст','Частка опублікованих коментарів, у яких ви змінили чернетку. З цих правок щоп’ятниці оновлюється ваш голос.')+'</div>';
  h+=run?'<p class="line">Останній запуск '+dt(run.day)+': перевірено профілів '+(run.checked??'—')+', публікували за 40 годин '+(run.posted_profiles??'—')+(run.spent_usd!=null?', витрачено $'+Number(run.spent_usd).toFixed(2):'')+'.'+(run.note?inf(run.note):'')+'</p>':'';
  if(stale)h+='<div class="warn">'+(run?'Радар не запускався з '+dt(run.day)+'. Перевірте комп’ютер і рутину Claude.':'Запусків ще не було.')+'</div>';
  const st={new:'Чекають',posted:'Опублікував',skipped:'Пропустив',all:'Усі'};
  h+='<div class="chips">'+Object.keys(st).map(k=>'<button data-state="'+k+'" class="'+(S.state===k?'on':'')+'">'+st[k]+'<span>'+(k==='all'?ds.length:(t[k]||0))+'</span></button>').join('')+'</div>';
  const inS=ds.filter(x=>S.state==='all'||x.state===S.state),bc={};for(const x of inS)bc[x.bucket]=(bc[x.bucket]||0)+1;
  if(Object.keys(bc).length>1)h+='<div class="chips"><button data-group="" class="'+(!S.group?'on':'')+'">Усі групи</button>'+Object.entries(bc).sort((x,y)=>y[1]-x[1]).map(([k,v])=>'<button data-group="'+esc(k)+'" class="'+(S.group===k?'on':'')+'">'+esc(G[k]||k)+'<span>'+v+'</span></button>').join('')+'</div>';
  const list=inS.filter(x=>!S.group||x.bucket===S.group);
  h+=list.length?list.map(card).join(''):'<div class="empty">Тут порожньо. Новий список приходить щобудня зранку.</div>';
  const warm={};for(const x of ds){if(x.state!=='posted')continue;const k=x.profile_url||x.author;(warm[k]=warm[k]||{a:x.author,u:x.profile_url,g:x.bucket,n:0,l:''}).n++;if((x.state_at||'')>warm[k].l)warm[k].l=x.state_at}
  const w=Object.values(warm).sort((x,y)=>y.n-x.n);
  if(w.length)h+='<h2>Кого вже прогріли'+inf('Від двох ваших коментарів людина вас бачила. Тепер можна додавати в контакти.')+'</h2><div class="tw"><table><thead><tr><th>Людина</th><th>Група</th><th>Коментарів</th><th>Останній</th></tr></thead><tbody>'+w.map(x=>'<tr><td>'+a(x.u,x.a)+'</td><td>'+esc(G[x.g]||x.g)+'</td><td>'+x.n+'</td><td>'+dt(x.l)+'</td></tr>').join('')+'</tbody></table></div>';
  return h;
}
function card(x){
  const txt=x.state==='posted'&&x.final_comment?x.final_comment:(x.comment||''),ini=(x.author||'?').split(/\s+/).map(w=>w[0]||'').join('').slice(0,2).toUpperCase();
  const st=x.state==='posted'?'<span class="pill ok">опублікував '+dt(x.state_at)+'</span>':x.state==='skipped'?'<span class="pill">пропустив · '+esc(SK[x.skip_reason]||'інше')+'</span>':'';
  const body=x.post_text?'<p class="x">'+esc(x.post_text)+'</p>'+(x.post_text.length>280?'<button class="more" data-a="more">показати весь допис</button>':''):(x.about?'<p class="x">'+esc(x.about)+'</p>':'');
  const cnt=[x.reactions?x.reactions+' реакцій':'',x.comments_n?x.comments_n+' коментарів':''].filter(Boolean).join(' · ');
  const acts=x.state==='new'?'<button class="btn p" data-a="copy">Скопіювати і відкрити допис</button><button class="btn" data-a="posted">Опублікував</button><select aria-label="Причина пропуску">'+Object.entries(SK).map(([k,l])=>'<option value="'+k+'">'+l+'</option>').join('')+'</select><button class="btn" data-a="skip">Пропустити</button>':'<button class="btn" data-a="open">Відкрити допис</button><button class="btn" data-a="undo">Повернути в чергу</button>';
  return '<div class="card" data-id="'+x.id+'" data-post="'+esc(li(x.post_url))+'"><div class="post"><div class="who"><div class="av">'+esc(ini)+'</div><div><b>'+a(x.profile_url,x.author||'?')+'</b> <span class="pill">'+esc(G[x.bucket]||x.bucket)+'</span> '+st+'<div class="hl">'+esc(x.headline)+'</div><div class="t">'+(x.age_min!=null?age(x.age_min)+' на момент запуску · ':'')+dt(x.day)+(cnt?' · '+cnt:'')+(x.why?' · '+esc(x.why):'')+'</div></div></div>'+body+'</div><div class="me"><div class="t">Ваш коментар'+(x.ctype?' · '+esc(x.ctype):'')+'</div><textarea rows="4"'+(x.state!=='new'?' readonly':'')+'>'+esc(txt)+'</textarea><div class="acts">'+acts+'<span class="msg"></span></div></div></div>';
}
function people(){
  const ps=S.d.people;
  if(!ps.length)return '<div class="empty">Список ще порожній. Він оновлюється щопонеділка.</div>';
  const comp=ps.filter(x=>x.competitors),cl=ps.filter(x=>x.grp==='clients'),clc=cl.filter(x=>x.competitors),own=ps.filter(x=>x.own_n);
  const up=ps.reduce((m,x)=>x.updated>m?x.updated:m,'');
  let h='<div class="kpis">'+kpi(own.length,'під вашими дописами','Люди, які реагували чи коментували ваші дописи за 30 днів.')+kpi(ps.filter(x=>x.grp==='icp').length,'покупці','Заголовок або посада збіглися з вашим ICP, країна з ваших ринків перевірена окремо за балами.','hot')+kpi(cl.length,'клієнти й ліди','Люди з компаній, які в Twenty мають статус клієнта, колишнього клієнта чи ліда.')+kpi(clc.length,'клієнти під конкурентами','Ваш клієнт чи лід реагує на допис конкурента. Передайте власнику акаунта того ж дня.')+'</div><p class="line">Оновлено '+dt(up)+'. Під конкурентами показано людей за 14 днів, під вашими дописами за 30.</p>';
  if(clc.length)h+='<div class="warn"><b>Клієнти й ліди під дописами конкурентів:</b> '+clc.slice(0,8).map(x=>a(x.profile_url,x.name)+' ('+esc(x.competitors)+')').join(', ')+'</div>';
  const f={'':'Усі',clients:'Клієнти й ліди',icp:'Покупці',peers:'Колеги',copilots:'Суміжні',tl:'Лідери думок',_comp:'Під конкурентами',_none:'Без групи'};
  const cnt=k=>k===''?ps.length:k==='_comp'?comp.length:k==='_none'?ps.filter(x=>!x.grp).length:ps.filter(x=>x.grp===k).length;
  h+='<div class="chips">'+Object.keys(f).map(k=>'<button data-rgroup="'+k+'" class="'+(S.rgroup===k?'on':'')+'">'+f[k]+'<span>'+cnt(k)+'</span></button>').join('')+'</div>';
  const list=ps.filter(x=>S.rgroup===''?1:S.rgroup==='_comp'?x.competitors:S.rgroup==='_none'?!x.grp:x.grp===S.rgroup).slice(0,200);
  h+='<div class="tw"><table><thead><tr><th>Людина</th><th>Група</th><th>Рівень'+inf('🔥 три і більше різних дописи, 🟡 два, ⚪ один.')+'</th><th>Реакції</th><th>Коментарі</th><th>Під чиїми дописами</th><th>Останній</th></tr></thead><tbody>'+list.map(x=>'<tr'+(x.grp==='clients'&&x.competitors?' class="alert"':'')+'><td>'+a(x.profile_url,x.name||'?')+'<small>'+esc([x.headline,x.company].filter(Boolean).join(' · ').slice(0,110))+'</small></td><td>'+esc(G[x.grp]||'—')+(x.status?'<small>'+esc(x.status)+'</small>':'')+'</td><td>'+esc(x.level)+'</td><td>'+(x.reactions||0)+'</td><td>'+(x.comments||0)+'</td><td>'+[x.own_n?'ваші':'',esc(x.competitors)].filter(Boolean).join(', ')+'</td><td>'+dt(x.last_at)+'</td></tr>').join('')+'</tbody></table></div>';
  return h;
}
async function act(c,body,m){
  const r=await fetch('/api/state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:+c.dataset.id,...body})});
  const j=await r.json().catch(()=>({}));
  if(!r.ok){m.textContent='Не збереглось: '+(j.error||r.status);return}
  await load();
}
document.addEventListener('click',async e=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.dataset.tab){S.tab=b.dataset.tab;return draw()}
  if(b.dataset.days){S.days=+b.dataset.days;return load()}
  if(b.dataset.state){S.state=b.dataset.state;S.group='';return draw()}
  if(b.dataset.group!==undefined){S.group=b.dataset.group;return draw()}
  if(b.dataset.rgroup!==undefined){S.rgroup=b.dataset.rgroup;return draw()}
  const c=b.closest('.card');if(!c)return;
  const m=c.querySelector('.msg'),ta=c.querySelector('textarea'),u=c.dataset.post;
  if(b.dataset.a==='more'){c.querySelector('.x').classList.add('open');b.remove()}
  if(b.dataset.a==='copy'){try{await navigator.clipboard.writeText(ta.value);m.textContent='Скопійовано'}catch{ta.select();m.textContent='Скопіюйте вручну'}if(u)window.open(u,'_blank','noopener')}
  if(b.dataset.a==='open'&&u)window.open(u,'_blank','noopener');
  if(b.dataset.a==='posted')await act(c,{action:'posted',comment:ta.value},m);
  if(b.dataset.a==='skip')await act(c,{action:'skipped',reason:c.querySelector('select').value},m);
  if(b.dataset.a==='undo')await act(c,{action:'undo'},m);
});
load();
</script></body></html>`;
