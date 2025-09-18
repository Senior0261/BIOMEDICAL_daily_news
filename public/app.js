console.log("app.js loaded ✅ v2025-09-18-3");

const TZ = "Asia/Tokyo";

function getParam(name){ return new URL(location.href).searchParams.get(name); }
function todayJST(){
  return new Intl.DateTimeFormat("en-CA",{timeZone:TZ,year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
}
function fmtDateISOToJP(d){
  try{
    return new Intl.DateTimeFormat("zh-CN",{timeZone:TZ,year:"numeric",month:"2-digit",day:"2-digit",weekday:"short"}).format(new Date(d)).replace(/\//g,"-");
  }catch{ return d }
}
function fmtISO(d){
  if(!d) return "";
  try{
    return new Intl.DateTimeFormat("zh-CN",{timeZone:TZ,year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date(d)).replace(/\//g,"-");
  }catch{ return d }
}
async function fetchJSON(url){
  const r = await fetch(url + (url.includes("?")?"&":"?") + "t=" + Date.now(), { cache:"no-store" });
  if(!r.ok) throw new Error("not found: "+url);
  return await r.json();
}

// 全局数据
let data = { date:"", items:{ ai_biomed:[], microfluidics:[], bioinfo:[] } };
const state = { cat:"ai_biomed", q:"" };

// 论文/新闻判定（基于 tags）
function isPaper(it){
  const tags = (it.tags || []).map(s => s.toLowerCase());
  return tags.includes("peer-reviewed") || tags.includes("preprint") || tags.includes("journal");
}

// 搜索过滤
function matchQuery(it, q){
  if(!q) return true;
  const hay = [it.title||"", it.summary||"", it.source||"", ...(it.tags||[])].join(" ").toLowerCase();
  return hay.includes(q.toLowerCase());
}

// —— 卡片渲染：新闻（含封面）
function cardNews(it){
  const time = fmtISO(it.time);
  const tags = (it.tags||[]).map(t=>`<span class="chip">${t}</span>`).join("");
  const host = (()=>{ try{ return new URL(it.url).host; }catch{ return ""; } })();
  const cover = (it.cover && it.cover.trim())
    ? it.cover.trim()
    : (host ? `https://www.google.com/s2/favicons?sz=256&domain=${host}` : "");

  return `
    <article class="card">
      ${cover ? `<img class="thumb" src="${cover}" alt="">` : ``}
      <div class="content">
        <h3 class="title"><a href="${it.url}" target="_blank" rel="noopener">${it.title||""}</a></h3>
        <div class="meta"><span>来源：${it.source||"未知"}</span>${time?`<span>· 发布：${time}</span>`:""}</div>
        <p class="desc">${it.summary||""}</p>
        <div class="chips">${tags}</div>
      </div>
      <div class="foot">
        <div class="src">外链：${host?`<a href="${it.url}" target="_blank" rel="noopener">${host}</a>`:""}</div>
        <a class="btn" href="${it.url}" target="_blank" rel="noopener">前往阅读 ↗</a>
      </div>
    </article>
  `;
}

// —— 卡片渲染：论文（无封面，紧凑）
function cardPaper(it){
  const time = fmtISO(it.time);
  const tags = (it.tags||[]).map(t=>`<span class="chip">${t}</span>`).join("");
  const host = (()=>{ try{ return new URL(it.url).host; }catch{ return ""; } })();
  return `
    <article class="card compact">
      <div class="content">
        <h3 class="title"><a href="${it.url}" target="_blank" rel="noopener">${it.title||""}</a></h3>
        <div class="meta"><span>来源：${it.source||"未知"}</span>${time?`<span>· 发布：${time}</span>`:""}</div>
        <div class="chips">${tags}</div>
        <p class="desc">${it.summary||""}</p>
      </div>
      <div class="foot">
        <div class="src">外链：${host?`<a href="${it.url}" target="_blank" rel="noopener">${host}</a>`:""}</div>
        <a class="btn" href="${it.url}" target="_blank" rel="noopener">查看论文 ↗</a>
      </div>
    </article>
  `;
}

function renderSplit(catKey){
  const all = (data.items && data.items[catKey]) ? data.items[catKey] : [];
  const filtered = all.filter(it => matchQuery(it, state.q));
  const papers = filtered.filter(isPaper);
  const news   = filtered.filter(it => !isPaper(it));

  // 容器
  const gPapers = document.getElementById(`grid-${catKey}-papers`);
  const gNews   = document.getElementById(`grid-${catKey}-news`);
  const ePapers = document.getElementById(`empty-${catKey}-papers`);
  const eNews   = document.getElementById(`empty-${catKey}-news`);

  if (gPapers) gPapers.innerHTML = papers.map(cardPaper).join("");
  if (gNews)   gNews.innerHTML   = news.map(cardNews).join("");

  if (ePapers) ePapers.hidden = papers.length > 0;
  if (eNews)   eNews.hidden   = news.length > 0;
}

function mount(){
  // 顶部日期 + 总数
  const counts = ["ai_biomed","microfluidics","bioinfo"].map(k => (data.items?.[k]?.length || 0));
  const total = counts.reduce((a,b)=>a+b,0);
  const todayEl = document.getElementById("today");
  if (todayEl) todayEl.textContent = `今天（日本时区）：${fmtDateISOToJP(data.date)} · 共 ${total} 条`;

  // 每类计数
  const c1 = document.getElementById("count-ai_biomed");
  const c2 = document.getElementById("count-microfluidics");
  const c3 = document.getElementById("count-bioinfo");
  if (c1) c1.textContent = `· ${data.items.ai_biomed.length} 条`;
  if (c2) c2.textContent = `· ${data.items.microfluidics.length} 条`;
  if (c3) c3.textContent = `· ${data.items.bioinfo.length} 条`;

  // 选项卡样式 & 显示切换
  document.querySelectorAll(".tab").forEach(t => {
    t.classList.toggle("active", t.dataset.cat === state.cat);
  });
  ["ai_biomed","microfluidics","bioinfo"].forEach(cat => {
    const sec = document.getElementById(cat);
    if (sec) sec.style.display = (cat === state.cat) ? "block" : "none";
  });

  // 渲染分区
  renderSplit("ai_biomed");
  renderSplit("microfluidics");
  renderSplit("bioinfo");

  console.log("mount() done ✔", {
    ai: data.items.ai_biomed.length,
    micro: data.items.microfluidics.length,
    bio: data.items.bioinfo.length
  });
}

// 事件
function bindEvents(){
  const q = document.getElementById("q");
  if (q) q.addEventListener("input", e => { state.q = e.target.value.trim(); mount(); });
  const p = document.getElementById("printBtn");
  if (p) p.onclick = () => window.print();
  const c = document.getElementById("copyMD");
  if (c) c.onclick = async () => {
    const url = `./data/${data.date}.md`;
    try {
      const r = await fetch(url, { cache: "no-store" });
      if(r.ok){ const txt = await r.text(); await navigator.clipboard.writeText(txt); alert("已复制今日 Markdown 摘要"); return; }
    } catch {}
    alert("未找到今日 Markdown 文件");
  };
  document.querySelectorAll(".tab").forEach(t => {
    t.addEventListener("click", () => { state.cat = t.dataset.cat; mount(); });
  });
}

// 启动
async function boot(){
  try{
    const d = getParam("date") || todayJST();
    try {
      data = await fetchJSON(`./data/${d}.json`);
    } catch {
      const dt = new Date(d); dt.setDate(dt.getDate()-1);
      data = await fetchJSON(`./data/${dt.toISOString().slice(0,10)}.json`);
    }
    bindEvents();
    mount();
  } catch (e){
    console.error("启动失败：", e);
    bindEvents();
    mount();
  }
}

boot();
