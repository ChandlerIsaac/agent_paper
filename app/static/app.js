"use strict";
const $ = id => document.getElementById(id);
let user=null, kb="", thread="", busy=false, threads=[], docs=[], toastTimer;
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n}
function notify(message){$("toast").textContent=message;$("toast").hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$("toast").hidden=true,6000)}
async function api(path, options={}){
  const headers={"X-ResearchMate":"1",...options.headers};
  if(options.body && !(options.body instanceof FormData)){headers["Content-Type"]="application/json";options.body=JSON.stringify(options.body)}
  const response=await fetch("/api"+path,{...options,headers,credentials:"same-origin"});
  if(!response.ok){let data;try{data=await response.json()}catch{data={detail:"服务器返回异常响应"}}
    if(response.status===401&&!path.startsWith("/auth/"))showAuth();
    throw new Error(typeof data.detail==="string"?data.detail:"请检查输入格式")}
  return response;
}
async function data(path,options){return (await api(path,options)).json()}
function bind(id,fn){$(id).addEventListener("click",()=>Promise.resolve().then(fn).catch(e=>notify(e.message)))}
function guard(){if(busy)throw new Error("当前任务处理中，请完成后再切换");}
function setBusy(value){busy=value;$("send").disabled=value;$("send").textContent=value?"处理中…":"发送 ↑";$("uploadButton").disabled=value;$("question").disabled=value}
function showAuth(){user=null;kb="";thread="";$("messages").replaceChildren();$("threads").replaceChildren();$("documents").replaceChildren();$("notes").replaceChildren();$("sourcePanel").hidden=true;if(!$("auth").open)$("auth").showModal()}
$("auth").addEventListener("cancel",e=>e.preventDefault());
async function authenticate(register=false){
  if(!$("authForm").reportValidity())return;
  $("authError").textContent="";
  try{user=await data("/auth/"+(register?"register":"login"),{method:"POST",body:{username:$("username").value,password:$("password").value}});
    $("password").value="";await loadWorkspace();$("auth").close()}
  catch(e){$("authError").textContent=e.message}
}
$("authForm").addEventListener("submit",e=>{e.preventDefault();authenticate()});
bind("register",()=>authenticate(true));
bind("logout",async()=>{guard();await data("/auth/logout",{method:"POST"});showAuth()});
async function loadWorkspace(){
  $("currentUser").textContent=user.username;
  const libraries=await data("/knowledge-bases");
  $("kbSelect").replaceChildren(...libraries.map(x=>{const o=el("option",x.name);o.value=x.id;return o}));
  kb=libraries.some(x=>x.id===kb)?kb:(libraries[0]?.id||"");
  $("kbSelect").value=kb;
  await refreshThreads();
  const previous=localStorage.getItem("researchmate.thread."+user.id);
  if(previous&&threads.some(x=>x.id===previous)){await selectThread(previous)}
  else{thread="";emptyChat();await refreshResources()}
}
async function refreshThreads(){
  threads=await data("/conversations");
  $("threads").replaceChildren(...threads.map(x=>{const b=el("button",x.title,x.id===thread?"active":"");b.title=x.title;b.onclick=()=>selectThread(x.id).catch(e=>notify(e.message));return b}));
}
function emptyChat(){$("chatTitle").textContent="开始一段有依据的对话";const box=el("div",undefined,"empty");box.append(el("div","✧","orb"),el("h2","从一个好问题开始"),el("p","选择知识库，上传论文，然后开始研究。"));$("messages").replaceChildren(box)}
async function selectThread(id){
  guard();const conv=threads.find(x=>x.id===id);if(!conv)return;
  thread=id;kb=conv.knowledge_base_id;$("kbSelect").value=kb;$("chatTitle").textContent=conv.title;
  localStorage.setItem("researchmate.thread."+user.id,thread);
  const history=await data("/conversations/"+thread+"/messages");$("messages").replaceChildren();
  history.forEach(x=>renderMessage(x.role,x.content,x));
  await refreshThreads();await refreshResources();scrollChat();
}
async function newChat(){guard();if(!kb)throw new Error("请先创建知识库");const conv=await data("/conversations",{method:"POST",body:{knowledge_base_id:kb}});
  await refreshThreads();await selectThread(conv.id);$("question").focus()}
bind("newChat",newChat);
bind("createKb",async()=>{guard();const name=prompt("知识库名称");if(!name?.trim())return;const result=await data("/knowledge-bases",{method:"POST",body:{name:name.trim()}});localStorage.removeItem("researchmate.thread."+user.id);kb=result.id;thread="";await loadWorkspace()});
$("kbSelect").onchange=async()=>{try{guard();kb=$("kbSelect").value;thread="";localStorage.removeItem("researchmate.thread."+user.id);emptyChat();await refreshThreads();await refreshResources()}catch(e){$("kbSelect").value=kb;notify(e.message)}};
bind("renameChat",async()=>{guard();if(!thread)return;const title=prompt("新的会话名称",$("chatTitle").textContent);if(!title?.trim())return;await data("/conversations/"+thread,{method:"PATCH",body:{title:title.trim()}});await refreshThreads();$("chatTitle").textContent=title});
bind("deleteChat",async()=>{guard();if(!thread||!confirm("删除此会话及持久化状态？此操作不可恢复。"))return;await data("/conversations/"+thread,{method:"DELETE"});localStorage.removeItem("researchmate.thread."+user.id);thread="";emptyChat();await refreshThreads()});
function scrollChat(){$("messages").scrollTop=$("messages").scrollHeight}
function formatDuration(seconds){const total=Math.max(0,Math.round(Number(seconds)||0));if(total<1)return"用时 < 1 秒";const minutes=Math.floor(total/60),rest=total%60;return minutes?"用时 "+minutes+" 分 "+rest+" 秒":"用时 "+rest+" 秒"}
function formatUsage(usage){if(!usage)return null;if(!usage.reported)return"Token 用量未返回";return"Token "+Number(usage.total_tokens||0).toLocaleString()+"（输入 "+Number(usage.input_tokens||0).toLocaleString()+" / 输出 "+Number(usage.output_tokens||0).toLocaleString()+"）"}
function traceBox(items=[],duration,usage,opened=false){const d=el("details",undefined,"trace");d.open=opened;const summary=el("summary");summary.append(el("span","执行过程 · "+items.length+" 个阶段"));const metrics=el("span",undefined,"trace-metrics");if(duration!==undefined&&duration!==null)metrics.append(el("span",formatDuration(duration),"trace-duration"));const tokenText=formatUsage(usage);if(tokenText)metrics.append(el("span",tokenText,"trace-tokens"));if(metrics.childNodes.length)summary.append(metrics);d.append(summary);const list=el("ol");items.forEach(x=>list.append(el("li",x.detail+(x.query?"\n搜索词："+x.query:""))));d.append(list);return d}
function safeUrl(url){try{const u=new URL(url);return ["https:","http:"].includes(u.protocol)?u.href:null}catch{return null}}
function renderInline(parent,text){
  const pattern=/(\*\*([^*]+)\*\*|`([^`\n]+)`|\[([^\]\n]+)\]\(([^)\s]+)\)|\*([^*\n]+)\*)/g;let cursor=0,match;
  while((match=pattern.exec(text))){parent.append(document.createTextNode(text.slice(cursor,match.index)));let node;
    if(match[2]!==undefined)node=el("strong",match[2]);
    else if(match[3]!==undefined)node=el("code",match[3]);
    else if(match[4]!==undefined){const url=safeUrl(match[5]);node=url?el("a",match[4]):document.createTextNode(match[0]);if(url){node.href=url;node.target="_blank";node.rel="noopener noreferrer"}}
    else node=el("em",match[6]);parent.append(node);cursor=pattern.lastIndex}
  parent.append(document.createTextNode(text.slice(cursor)));
}
function renderMarkdown(container,markdown){
  container.replaceChildren();const lines=String(markdown||"").replace(/\r\n/g,"\n").split("\n"),fragment=document.createDocumentFragment();let i=0;
  const special=line=>/^\s*```|^#{1,6}\s+|^\s*[-*]\s+|^\s*\d+\.\s+|^\s*>\s?|^\s*---+\s*$/.test(line);
  while(i<lines.length){const line=lines[i];if(!line.trim()){i++;continue}
    if(/^\s*```/.test(line)){const code=[];i++;while(i<lines.length&&!/^\s*```/.test(lines[i]))code.push(lines[i++]);if(i<lines.length)i++;const pre=el("pre");pre.append(el("code",code.join("\n")));fragment.append(pre);continue}
    const heading=line.match(/^(#{1,6})\s+(.+)$/);if(heading){const h=el("h"+heading[1].length);renderInline(h,heading[2]);fragment.append(h);i++;continue}
    if(/^\s*[-*]\s+/.test(line)){const list=el("ul");while(i<lines.length&&/^\s*[-*]\s+/.test(lines[i])){const item=el("li");renderInline(item,lines[i].replace(/^\s*[-*]\s+/,""));list.append(item);i++}fragment.append(list);continue}
    if(/^\s*\d+\.\s+/.test(line)){const list=el("ol");while(i<lines.length&&/^\s*\d+\.\s+/.test(lines[i])){const item=el("li");renderInline(item,lines[i].replace(/^\s*\d+\.\s+/,""));list.append(item);i++}fragment.append(list);continue}
    if(/^\s*>\s?/.test(line)){const quote=el("blockquote");const parts=[];while(i<lines.length&&/^\s*>\s?/.test(lines[i]))parts.push(lines[i++].replace(/^\s*>\s?/,""));renderInline(quote,parts.join("\n"));fragment.append(quote);continue}
    if(/^\s*---+\s*$/.test(line)){fragment.append(el("hr"));i++;continue}
    const paragraph=[];while(i<lines.length&&lines[i].trim()&&!special(lines[i]))paragraph.push(lines[i++]);const p=el("p");renderInline(p,paragraph.join("\n"));fragment.append(p)
  }
  container.append(fragment);
}
function requestWebApproval(item){return new Promise(resolve=>{const dialog=$("webApproval");$("approvalProvider").textContent=item.provider||"公开搜索服务";$("approvalQuery").textContent=item.query||"（空）";let settled=false,timer;
  const finish=accepted=>{if(settled)return;settled=true;clearTimeout(timer);dialog.close();resolve(accepted)};$("acceptWeb").onclick=()=>finish(true);$("rejectWeb").onclick=()=>finish(false);dialog.oncancel=e=>{e.preventDefault();finish(false)};timer=setTimeout(()=>finish(false),55000);dialog.showModal()})}
function readableSource(c){if(c.kind!=="web"||typeof c.snippet!=="string"||!c.snippet.trim().startsWith("{"))return c.snippet;try{const item=JSON.parse(c.snippet),published=item.published||item["published-print"]||item["published-online"]||{},parts=published["date-parts"]?.[0]||[],event=item.event||{},first=value=>Array.isArray(value)?value[0]||"":value||"",fields=[["标题",first(item.title)],["出版载体",first(item["container-title"])],["文献类型",item.type],["发表日期",parts.join("-")],["出版方",item.publisher],["会议名称",event.name],["会议简称",event.acronym],["会议地点",event.location],["DOI",item.DOI]];return fields.filter(x=>x[1]).map(x=>x[0]+"："+x[1]).join("\n")}catch{return c.snippet}}
function renderMessage(role,text,result={}){
  const box=el("article",undefined,"message "+role);box.append(el("div",role==="user"?"你":"RESEARCHMATE","role"));
  if(result.trace?.length)box.append(traceBox(result.trace,result.duration_seconds,result.usage,result.trace_open));
  const body=el("div",undefined,"body markdown-body");renderMarkdown(body,text);box.append(body);
  if(result.citations?.length){
    const sources=el("div",undefined,"sources");
    result.citations.forEach(c=>{const d=el("details");const kind=c.kind==="web"?"网页":c.kind==="note"?"个人笔记":"论文";
      d.append(el("summary","[来源 "+c.number+"] "+kind+" · "+c.source+(c.page?" · 第 "+c.page+" 页":"")),el("p",readableSource(c)));
      if(c.kind==="web"&&safeUrl(c.url)){const a=el("a","打开来源 ↗");a.href=safeUrl(c.url);a.target="_blank";a.rel="noopener noreferrer";d.append(a)}
      if(c.kind==="document"&&c.document_id){const b=el("button","查看整页");b.onclick=()=>showPage(c.document_id,c.page).catch(e=>notify(e.message));d.append(b)}
      sources.append(d)});box.append(sources)
  }
  if(role==="assistant"&&text&&!result.pending){const b=el("button","＋ 保存为研究笔记","save-note");b.onclick=()=>{try{guard();switchTab("notes");$("noteTitle").value="研究结论";$("noteContent").value=text;$("noteTitle").focus()}catch(e){notify(e.message)}};box.append(b)}
  $("messages").append(box);return box;
}
$("question").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey&&!e.isComposing){e.preventDefault();$("chatForm").requestSubmit()}});
$("chatForm").addEventListener("submit",async e=>{
  e.preventDefault();if(busy)return;const question=$("question").value.trim();if(!question)return;
  let placeholder,accepted=false,received=false,ticker;
  try{
    if(!thread)await newChat();
    setBusy(true);$("messages").querySelector(".empty")?.remove();renderMessage("user",question);
    placeholder=renderMessage("assistant","请求处理中…",{pending:true});scrollChat();
    const response=await api("/chat/stream",{method:"POST",body:{knowledge_base_id:kb,thread_id:thread,question,allow_web:$("allowWeb").checked}});
    accepted=true;$("question").value="";
    const reader=response.body.getReader(),decoder=new TextDecoder();let buffer="",steps=[],liveText="",statusText="请求已接收";const started=Date.now();
    const updatePlaceholder=()=>{if(!placeholder)return;const elapsed=Math.floor((Date.now()-started)/1000),opened=placeholder.querySelector(".trace")?.open||false,nodes=[el("div","RESEARCHMATE","role"),traceBox(steps,elapsed,null,opened),el("div",statusText+" · 已等待 "+elapsed+" 秒","live-status")];if(liveText){const body=el("div",undefined,"body markdown-body");renderMarkdown(body,liveText);nodes.push(body)}placeholder.replaceChildren(...nodes)};
    ticker=setInterval(updatePlaceholder,1000);updatePlaceholder();
    while(true){const {value,done}=await reader.read();buffer+=done?decoder.decode():decoder.decode(value,{stream:true});buffer=buffer.replace(/\r\n/g,"\n");
      let end;while((end=buffer.indexOf("\n\n"))>=0){const frame=buffer.slice(0,end);buffer=buffer.slice(end+2);const lines=frame.split("\n");
        const name=lines.find(x=>x.startsWith("event:"))?.slice(6).trim();const payload=lines.filter(x=>x.startsWith("data:")).map(x=>x.slice(5).trim()).join("\n");if(!payload)continue;const item=JSON.parse(payload);
        if(name==="status"){steps.push(item);statusText=item.detail;if(item.stage==="web_start")statusText="🌐 "+statusText+(item.provider?"（"+item.provider+"）":"");updatePlaceholder();scrollChat()}
        if(name==="approval"){statusText="等待你决定是否允许联网";updatePlaceholder();const accepted=await requestWebApproval(item);await data("/chat/approvals/"+item.approval_id,{method:"POST",body:{accepted}});steps.push({stage:"approval",detail:accepted?"你已允许本轮联网检索":"你已拒绝联网，本轮仅使用本地证据",query:item.query});statusText=steps.at(-1).detail;updatePlaceholder()}
        if(name==="token"){liveText+=item.text||"";statusText="正在接收模型回答";updatePlaceholder();scrollChat()}
        if(name==="result"){const opened=placeholder.querySelector(".trace")?.open||false;placeholder.remove();placeholder=null;renderMessage("assistant",item.answer,{...item,trace_open:opened});received=true;scrollChat()}
        if(name==="error")throw new Error(item.detail);
      }if(done)break
    }
    if(!received)throw new Error("连接中断。服务器可能仍在处理，请稍后重新打开此会话查看结果。");
    await refreshThreads();$("chatTitle").textContent=threads.find(x=>x.id===thread)?.title||"研究对话";
  }catch(error){if(placeholder)placeholder.querySelector(".body").textContent=error.message;$("question").value=question;notify(error.message)}
  finally{clearInterval(ticker);setBusy(false);$("question").focus()}
});
async function refreshResources(){
  $("sourcePanel").hidden=true;
  if(!kb){docs=[];$("documents").replaceChildren(el("p","创建知识库后上传文档","muted"));$("notes").replaceChildren();$("graph").replaceChildren();return}
  docs=await data("/knowledge-bases/"+kb+"/documents");
  $("documents").replaceChildren(...docs.map(doc=>{const c=el("div",undefined,"card");c.append(el("h4",doc.filename),el("p",doc.page_count+" 页 · "+doc.chunk_count+" 个切片"));
    const actions=el("div",undefined,"row");const view=el("button","查看");view.onclick=()=>showPage(doc.id,1).catch(e=>notify(e.message));
    const rebuild=el("button","重建索引");rebuild.onclick=()=>operation(async()=>{await data("/knowledge-bases/"+kb+"/documents/"+doc.id+"/reindex",{method:"POST"});notify("索引已重建")});
    const remove=el("button","删除","danger");remove.onclick=()=>operation(async()=>{if(confirm("删除文档及索引？此操作不可恢复。"))await data("/knowledge-bases/"+kb+"/documents/"+doc.id,{method:"DELETE"})});
    actions.append(view,rebuild,remove);c.append(actions);return c}));
  if(!docs.length)$("documents").append(el("p","还没有文档","muted"));
  await loadNotes();if(!$("graphPanel").hidden)await loadGraph();
}
async function operation(fn){try{guard();setBusy(true);await fn();await refreshResources()}catch(e){notify(e.message)}finally{setBusy(false)}}
$("uploadForm").addEventListener("submit",e=>{e.preventDefault();operation(async()=>{if(!kb)throw new Error("请先创建知识库");const file=$("file").files[0];if(!file)return;if(file.size>50*1024*1024)throw new Error("文件不能超过 50 MB");
  const form=new FormData();form.append("file",file);$("uploadButton").textContent="正在上传、解析和索引…";
  try{const r=await data("/knowledge-bases/"+kb+"/documents",{method:"POST",body:form});notify("完成："+r.page_count+" 页，"+r.chunk_count+" 个切片");$("file").value=""}finally{$("uploadButton").textContent="上传并建立索引"}
})});
bind("deleteKb",()=>operation(async()=>{if(!kb||!confirm("删除整个知识库、原始文件、笔记和关联会话？此操作不可恢复。"))return;await data("/knowledge-bases/"+kb,{method:"DELETE"});thread="";kb="";localStorage.removeItem("researchmate.thread."+user.id);await loadWorkspace()}));
function switchTab(name){document.querySelectorAll("[data-tab]").forEach(b=>b.classList.toggle("active",b.dataset.tab===name));["documents","notes","graph"].forEach(x=>$(x+"Panel").hidden=x!==name);if(name==="graph")loadGraph().catch(e=>notify(e.message))}
document.querySelectorAll("[data-tab]").forEach(b=>b.onclick=()=>switchTab(b.dataset.tab));
async function loadNotes(){
  if(!kb)return;const query=$("noteQuery").value.trim();const notes=await data("/knowledge-bases/"+kb+"/notes"+(query?"?query="+encodeURIComponent(query):""));
  $("notes").replaceChildren(...notes.map(n=>{const c=el("div",undefined,"card");c.append(el("h4",n.title),el("p",n.content));if(n.score!==undefined)c.append(el("p","语义相似度 "+n.score.toFixed(3)+"（非置信度）"));
    const remove=el("button","删除笔记","danger");remove.onclick=()=>operation(async()=>{if(confirm("删除这条笔记？"))await data("/knowledge-bases/"+kb+"/notes/"+n.id,{method:"DELETE"})});c.append(remove);return c}));
}
bind("searchNotes",loadNotes);
$("noteForm").addEventListener("submit",e=>{e.preventDefault();operation(async()=>{if(!kb)throw new Error("请先选择知识库");await data("/knowledge-bases/"+kb+"/notes",{method:"POST",body:{title:$("noteTitle").value,content:$("noteContent").value}});$("noteTitle").value="";$("noteContent").value="";notify("笔记已保存并建立语义索引")})});
async function showPage(doc,page){const item=await data("/knowledge-bases/"+kb+"/documents/"+doc+"/pages/"+page);$("sourceTitle").textContent=item.source+" · 第 "+page+" 页";$("sourceText").textContent=item.content;$("sourcePanel").hidden=false;$("sourcePanel").scrollIntoView({behavior:"smooth",block:"nearest"})}
bind("closeSource",()=>$("sourcePanel").hidden=true);
function svgElement(tag,attrs,text){const n=document.createElementNS("http://www.w3.org/2000/svg",tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n}
async function loadGraph(){
  if(!kb)return;const result=await data("/knowledge-bases/"+kb+"/graph"),svg=$("graph");svg.replaceChildren();$("pagePicker").replaceChildren();
  const nodes=result.nodes.filter(x=>x.kind==="document"),height=Math.max(180,nodes.length*76+40);svg.setAttribute("viewBox","0 0 300 "+height);svg.style.height=height+"px";
  const rootY=height/2;
  nodes.forEach((n,i)=>{const y=40+i*76;svg.append(svgElement("path",{d:"M 62 "+rootY+" C 115 "+rootY+", 100 "+y+", 148 "+y,fill:"none",stroke:"#c7d8d9","stroke-width":1.5}))});
  svg.append(svgElement("circle",{cx:48,cy:rootY,r:28,fill:"#397b78"}),svgElement("text",{x:48,y:rootY+4,"text-anchor":"middle",fill:"white","font-size":11},"知识库"));
  nodes.forEach((n,i)=>{const y=40+i*76,g=svgElement("g",{class:"graph-node",tabindex:0,role:"button","aria-label":n.label});
    g.append(svgElement("rect",{x:143,y:y-23,width:150,height:46,rx:9,fill:"white",stroke:"#dce5ea"}),svgElement("title",{},n.label),svgElement("text",{x:151,y:y-3,"font-size":10,fill:"#243346"},n.label.length>20?n.label.slice(0,20)+"…":n.label),svgElement("text",{x:151,y:y+13,"font-size":9,fill:"#738096"},n.pages+" 页 · 点击展开"));
    const expand=()=>{const container=$("pagePicker");container.replaceChildren(el("h4",n.label));const pages=el("div",undefined,"page-buttons");
      for(let p=1;p<=Math.min(n.pages,100);p++){const b=el("button","第 "+p+" 页");b.onclick=()=>showPage(n.id,p).catch(e=>notify(e.message));pages.append(b)}container.append(pages);
      if(n.pages>100){const input=el("input");input.type="number";input.min=1;input.max=n.pages;input.placeholder="输入页码";const b=el("button","查看页面");b.onclick=()=>showPage(n.id,Number(input.value)).catch(e=>notify(e.message));container.append(input,b)}
    };g.onclick=expand;g.onkeydown=e=>{if(e.key==="Enter")expand()};svg.append(g)});
}
(async()=>{try{user=await data("/auth/me");await loadWorkspace()}catch{showAuth()}})();
