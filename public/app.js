// ====== 版本日志 ======
console.log("app.js loaded ✅ v2025-09-18-2");

// ====== 工具 & 时区 ======
const TZ = "Asia/Tokyo";

function getParam(name){
  const u = new URL(location.href);
  return u.searchParams.get(name);
}
function todayJST() {
  const now = new Date();
  const opt = { timeZone: TZ, year:"numeric", month:"2-digit", day:"2-digit" };
  return new Intl.DateTimeFormat("en-CA", opt).format(now); // YYYY-MM-DD
}
function fmtDateISOToJP(d){
  try{
    const dt = new Date(d);
    const opt = { timeZone: TZ, year:"numeric", month:"2-digit", day:"2-digit", weekday:"short" };
    return new Intl.DateTimeFormat("zh-CN", opt).format(dt).replace(/\//g,"-");
  }catch{ return d }
}
function fmtISO(d){
  if(!d) return "";
  try{
    const dt = new Date(d);
    const opt = { timeZone: TZ, year:"numeric", month:"2-digit", day:"2-digit" };
    return new Intl.DateTimeFormat("zh-CN", opt).format(dt).replace(/\//g,"-");
  }catch{ return d }
}
async function fetchJSON(url){
  const bust = (url.includes("?") ? "&" : "?") + "t=" + Date.now();
  const r = await fetch(url + bust, { cache: "no-store" });
  if(!r.ok) throw new Error("not found: " + url);
  return await r.json();
}

// ====== 全局数据状态 ======
let data = { date: "", items: { ai_biomed:[], microfluidics:[], bioinfo:[] } };
const state = { cat: "ai_biomed", q: "" };

// ====== 过滤 & 渲染 ======
function matchQuery(it, q){
  if(!q) return true;
  const hay = [
    it.title || "",
    it.summary || "",
    it.source || "",
    ...(it.tags || [])
  ].join(" ").toLowerCase();
  return hay.includes(q.toLowerCase());
}

function card(it){
  const time = fmtISO(it.time);
  const tags = (it.tags || []).map(t => `<span class="chip">${t}</span>`).join("");
  const host = (() => { try { return new URL(it.url).host; } catch { return ""; } })();
  const cover = (it.cover && it.cover.trim())
    ? it.cover.trim()
    : "data:image/svg+xml;utf8," + encodeURIComponent(
        `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 600 338'>
           <rect width='100%' height='100%' fill='#ddd'/>
           <text x='50%' y='50%' text-anchor='middle' fill='#777'
                 font-size='18' font-family='system-ui'>No Cover</text>
         </svg>`
      );

  return `
    <article class="card">
      <img class="thumb" src="${cover}" alt="">
      <div class="content">
        <h3 class="title"><a href="${it.url}" target="_blank" rel="noopener">${it.title || ""}</a></h3>
        <div class="meta"><span>来源：${it.source || "未知"}</span>${time?`<span>· 发布：${time}</span>`:""}</div>
        <p class="desc">${it.summary || ""}</p>
        <div class="chips">${tags}</div>
      </div>
      <div class="foot">
        <div class="src">外链：${host ? `<a href="${it.url}" target="_blank" rel="noopener">${host}</a>` : ""}</div>
        <a class="btn" href="${it.url}" target="_blank" rel="noopener">前往阅读 ↗</a>
      </div>
    </article>
  `;
}

function renderCategory(catKey){
  const grid = document.getElementById(`grid-${catKey}`);
  const empty = document.getElementById(`empty-${catKey}`);
  const arrAll = (data.items && data.items[catKey]) ? data.items[catKey] : [];
  const arr = arrAll.filter(it => matchQuery(it, state.q));

  grid.innerHTML = arr.map(card).join("");
  empty.hidden = arr.length > 0;
}

function mount(){
  // 顶部日期 + 总数
  const counts = ["ai_biomed","microfluidics","bioinfo"].map(k => (data.items?.[k]?.length || 0));
  const total = counts.reduce((a,b)=>a+b,0);
  const todayEl = document.getElementById("today");
  if (todayEl) {
    todayEl.textContent = `今天（日本时区）：${fmtDateISOToJP(data.date)} · 共 ${total} 条`;
  }

  // 显示计数
  const c1 = document.getElementById("count-ai_biomed");
  const c2 = document.getElementById("count-microfluidics");
  const c3 = document.getElementById("count-bioinfo");
  if (c1) c1.textContent = `· ${data.items.ai_biomed.length} 条`;
  if (c2) c2.textContent = `· ${data.items.microfluidics.length} 条`;
  if (c3) c3.textContent = `· ${data.items.bioinfo.length} 条`;

  // 选项卡样式
  document.querySelectorAll(".tab").forEach(t => {
    t.classList.toggle("active", t.dataset.cat === state.cat);
  });

  // 切换显示
  ["ai_biomed","microfluidics","bioinfo"].forEach(cat => {
    const sec = document.getElementById(cat);
    if (sec) sec.style.display = (cat === state.cat) ? "block" : "none";
  });

  // 渲染
  renderCategory("ai_biomed");
  renderCategory("microfluidics");
  renderCategory("bioinfo");

  console.log("mount() done ✔", {
    ai: data.items.ai_biomed.length,
    micro: data.items.microfluidics.length,
    bio: data.items.bioinfo.length
  });
}

// ====== 事件绑定 ======
function bindEvents(){
  const q = document.getElementById("q");
  if (q) q.addEventListener("input", e => {
    state.q = e.target.value.trim();
    mount();
  });
  const p = document.getElementById("printBtn");
  if (p) p.onclick = () => window.print();

  const c = document.getElementById("copyMD");
  if (c) c.onclick = async () => {
    const url = `./data/${data.date}.md`;
    try {
      const r = await fetch(url, { cache: "no-store" });
      if(r.ok){
        const txt = await r.text();
        await navigator.clipboard.writeText(txt);
        alert("已复制今日 Markdown 摘要");
        return;
      }
    } catch {}
    alert("未找到今日 Markdown 文件");
  };

  document.querySelectorAll(".tab").forEach(t => {
    t.addEventListener("click", () => { state.cat = t.dataset.cat; mount(); });
  });
}

// ====== 启动流程 ======
async function boot(){
  try{
    const d = getParam("date") || todayJST();
    try {
      data = await fetchJSON(`./data/${d}.json`);
    } catch {
      // 当天没有，退一天
      const dt = new Date(d); dt.setDate(dt.getDate() - 1);
      data = await fetchJSON(`./data/${dt.toISOString().slice(0,10)}.json`);
    }
    bindEvents();
    mount();
  } catch (e){
    console.error("启动失败：", e);
    // 渲染空状态
    bindEvents();
    mount();
  }
}

// defer 脚本：DOM 解析后执行
boot();
