"use strict";
const {test}=require("node:test"), assert=require("node:assert/strict"), fs=require("node:fs"), path=require("node:path"), vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"../static/lite.js"),"utf8");
const flush=async()=>{for(let i=0;i<7;i++)await new Promise(setImmediate);};
function fixture(){return {id:"p1",title:"NetHack long-horizon credit assignment",status:"idle",stage:"Contract accepted",error:null,
 messages:[{role:"assistant",content:"What counts as success?"},{role:"user",content:"Ascension, without adapting the checkpoint during evaluation."}],
 checklist:[{id:"objective",title:"Research objective",resolved:2,total:2,missing:[],summary:"Test credit assignment",fields:{objective:"Test credit assignment",task_kind:"environment"}},{id:"evaluation",title:"Evaluation protocol",resolved:7,total:7,missing:[],summary:"Success across fixed seeds",fields:{metric:"success_rate",max_steps:null}}],
 contract:{objective:"Test credit assignment",task_kind:"environment",metric:"success_rate",max_steps:null},proposal:null,sources:[],ready:true,model:{configured:true,calls:3,round_calls:3,limit:30},
 package:{status:"ready",version:"v1",url:"/api/projects/p1/lite/package",config_url:"/api/projects/p1/lite/config",preview_url:"/api/projects/p1/lite/preview",readme_url:"/api/projects/p1/lite/readme.md"},results:[]};}
function harness(data=fixture(),search="?project=p1",hash=""){
 const nodes=new Map(),calls=[],events={},timers=new Map(),storage=new Map();let nextTimer=0,nextUUID=0;
 class Node{
  constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.events={};this.attributes={};this._text="";this.value="";this.hidden=false;this.disabled=false;this.checked=false;this.files=[];this.scrollHeight=100;this.scrollTop=0;this.clientHeight=90;}
  set id(v){this._id=v;nodes.set(v,this);}get id(){return this._id;}
  set textContent(v){this._text=String(v);this.children=[];}get textContent(){return this._text+this.children.map(x=>x.textContent).join(" ");}
  append(...items){for(const n of items){this.children.push(n);n.parent=this;}}replaceChildren(...items){this.children=[];this._text="";this.append(...items);}
  setAttribute(k,v){this.attributes[k]=String(v);}removeAttribute(k){delete this.attributes[k];delete this[k];}addEventListener(k,v){this.events[k]=v;}focus(){this.focused=true;}showModal(){this.open=true;}close(){this.open=false;}
  querySelectorAll(selector){const all=[];for(const n of this.children){if(selector==="[data-mutation]"&&n.dataset.mutation)all.push(n);all.push(...n.querySelectorAll(selector));}return all;}
 }
 const $=id=>{if(!nodes.has(id)){const n=new Node("div");n.id=id;}return nodes.get(id);};
 const h={$,data,calls,timers,events,storage,handler:null,access:{private_mode:false,can_create_projects:true,auth_kind:"owner"},
  async click(id){const n=$(id);if(!n.disabled){if(id==="send-message")await $("message-form").events.submit({preventDefault(){}});else await n.events.click?.();}await flush();},
  async clickText(text){const n=[...nodes.values()].flatMap(n=>descendants(n)).find(n=>n.tag==="button"&&n.textContent===text);assert.ok(n,"Missing button: "+text);if(!n.disabled)await n.events.click?.();await flush();},
  async submitFor(id){let n=$(id);while(n&&n.tag!=="form")n=n.parent;assert.ok(n,"Form not found");await n.events.submit({preventDefault(){}});await flush();},
  async input(id,text){$(id).value=text;await $(id).events.input?.();await flush();}
 };
 function descendants(n){return [n,...n.children.flatMap(descendants)];}
 const location={origin:"https://testserver",search,hash},history={replaceState(_a,_b,url){h.url=url;}};
 const fetch=async(url,options)=>{calls.push({url,options});if(h.handler){const out=await h.handler(url,options);if(out)return out;}
  let body;if(url==="/api/access")body=h.access;else if(url==="/api/lite/projects")body=options.method?data:{projects:[{id:data.id,title:data.title}]};else body=data;
  return {ok:true,status:200,json:async()=>structuredClone(body)};};
 vm.runInNewContext(source,{document:{getElementById:$,createElement:tag=>new Node(tag)},window:{addEventListener:(k,v)=>events[k]=v},location,history,fetch,URL,URLSearchParams,AbortController,FormData,Date,crypto:{randomUUID:()=>"request-"+(++nextUUID)},
 sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k),key:i=>[...storage.keys()][i],get length(){return storage.size;}},localStorage:{setItem(){}},setTimeout:(f,ms)=>{timers.set(++nextTimer,{f,ms});return nextTimer;},clearTimeout:id=>timers.delete(id)});
 return h;
}
test("Opening Lite does not create a project or alter the Full workflow",async()=>{const h=harness(fixture(),"");await flush();assert.deepEqual(h.calls.map(c=>c.url),["/api/access"]);assert.equal(h.$("message-input").disabled,true);assert.equal(h.$("checklist").children.length,6);});
test("An existing Lite session loads saved messages and six coverage cards",async()=>{const h=harness();await flush();assert.equal(h.calls.filter(c=>c.options.method).length,0);assert.match(h.$("messages").textContent,/Ascension/);assert.equal(h.$("coverage").value,2);assert.equal(h.$("checklist").children.length,6);assert.equal(h.$("sources-button").disabled,false);});
test("Checklist details preserve an explicit no-step-limit decision",async()=>{const h=harness();await flush();await h.click("check-evaluation");assert.match(h.$("dialog-content").textContent,/No step limit/);assert.doesNotMatch(h.$("dialog-content").textContent,/Not recorded/);});
test("Source and model markup is displayed as literal text",async()=>{const f=fixture();f.messages=[{role:"assistant",content:'<img src=x onerror="steal()">'},{role:"user",content:"A reply."}];const h=harness(f);await flush();assert.match(h.$("messages").textContent,/<img src=x/);assert.equal(h.$("messages").children[0].children[1].children.length,0);});
test("Proposal acceptance is explicit and carries the current proposal identity",async()=>{const f=fixture();f.proposal={id:"proposal-1",summary:"Proposed scope",contract:{max_steps:null,metric:"success_rate"},evidence:{metric:{basis:"suggestion",excerpt:"Please confirm."}}};const h=harness(f);await flush();assert.equal(h.$("proposal-banner").hidden,false);await h.click("review-proposals");assert.match(h.$("dialog-content").textContent,/Agent suggestion/);assert.equal(h.calls.filter(c=>c.options.method).length,0);await h.clickText("Accept this definition");const call=h.calls.find(c=>c.url.endsWith("/accept"));assert.deepEqual(JSON.parse(call.options.body),{proposal_id:"proposal-1"});});
test("A proposal can be discarded without changing accepted evidence",async()=>{const f=fixture();f.proposal={id:"proposal-2",contract:{objective:"Speculation"}};const h=harness(f);await flush();await h.click("review-proposals");await h.clickText("Discard proposal");assert.deepEqual(JSON.parse(h.calls.find(c=>c.url.endsWith("/discard")).options.body),{proposal_id:"proposal-2"});});
test("Failed messages preserve the draft and reuse a stable request ID",async()=>{const h=harness();await flush();h.handler=async(url,options)=>{if(url.endsWith("/message"))throw new TypeError("Connection stopped");};await h.input("message-input","Use fixed evaluation seeds.");await h.click("send-message");assert.equal(h.$("message-input").value,"Use fixed evaluation seeds.");await h.click("send-message");const calls=h.calls.filter(c=>c.url.endsWith("/message"));assert.equal(calls.length,2);assert.equal(calls[0].options.body,calls[1].options.body);});
test("Queued work disables duplicate messages and schedules state polling",async()=>{const h=harness();await flush();h.handler=async url=>url.endsWith("/message")?{ok:true,json:async()=>({...fixture(),status:"working",stage:"Reading your answer"})}:null;await h.input("message-input","Use an episode count of 100.");await h.click("send-message");assert.equal(h.$("message-input").value,"");assert.equal(h.$("send-message").disabled,true);assert.equal(h.$("thinking").hidden,false);assert.ok([...h.timers.values()].some(t=>t.ms===1500));});
test("Provider errors expose retry without repeating the user message",async()=>{const f=fixture();f.status="error";f.error="Model temporarily unavailable";const h=harness(f);await flush();assert.equal(h.$("retry-request").hidden,false);await h.click("retry-request");assert.ok(h.calls.some(c=>c.url.endsWith("/retry")));assert.ok(!h.calls.some(c=>c.url.endsWith("/message")));});
test("Request limit offers another bounded round",async()=>{const f=fixture();f.model.round_calls=30;const h=harness(f);await flush();assert.equal(h.$("continue-round").hidden,false);assert.match(h.$("recovery-detail").textContent,/saved context/);await h.click("continue-round");assert.ok(h.calls.some(c=>c.url.endsWith("/continue")));});
test("A stale package has no download or preview links",async()=>{const f=fixture();f.package.status="stale";const h=harness(f);await flush();await h.click("package-button");assert.match(h.$("dialog-content").textContent,/Prepare a new package/);assert.doesNotMatch(h.$("dialog-content").textContent,/Download ZIP/);});
test("Artifact links are restricted to this session and origin",async()=>{const f=fixture();f.package.url="https://attacker.example/zip";f.package.config_url="https://attacker.example/config";f.package.preview_url="/api/projects/p2/lite/preview";f.package.readme_url="javascript:alert(1)";const h=harness(f);await flush();await h.click("package-button");assert.doesNotMatch(h.$("dialog-content").textContent,/Download ZIP|Download config|View challenge|Read README/);});
test("Evidence checks never imply an independently reproduced result",async()=>{const f=fixture();f.results=[{evidence_level:"evidence_checked",summary:{score:.5,metric:"success_rate"},received_at:"2026-11-05T12:00:00Z",limitations:"The service did not run the model."}];const h=harness(f);await flush();await h.click("results-button");assert.match(h.$("dialog-content").textContent,/Evidence checked · researcher-run/);assert.match(h.$("dialog-content").textContent,/did not run the model/);assert.doesNotMatch(h.$("dialog-content").textContent,/Independently reproduced/);});
test("Invalid result JSON receives an actionable error before submission",async()=>{const h=harness();await flush();await h.click("results-button");h.$("result-file").files=[{size:30,text:async()=>'{"summary":{}}'}];await h.$("result-file").events.change();await flush();assert.match(h.$("dialog-error").textContent,/manifest object and a results array/);assert.ok(!h.calls.some(c=>c.url.endsWith("/results")));});
test("A runner report submits only the manifest and episode evidence with an idempotency key",async()=>{const h=harness();await flush();await h.click("results-button");const report={manifest:{challenge_version:"v1",artifact_sha256:"a".repeat(64)},results:[{seed:42,status:"completed",score:1}],summary:{score:999}};h.$("result-file").files=[{size:100,text:async()=>JSON.stringify(report)}];await h.$("result-file").events.change();await h.submitFor("result-file");const body=JSON.parse(h.calls.find(c=>c.url.endsWith("/results")).options.body);assert.deepEqual(body.manifest,report.manifest);assert.deepEqual(body.results,report.results);assert.ok(body.request_id);assert.equal(body.summary,undefined);});
test("Stale package keeps result submission disabled",async()=>{const f=fixture();f.package.status="stale";const h=harness(f);await flush();await h.click("results-button");const mutation=h.$("dialog-content").querySelectorAll("[data-mutation]")[0];assert.equal(mutation.disabled,true);});
test("A new session requires explicit storage acceptance and email",async()=>{const h=harness(fixture(),"");await flush();await h.click("new-button");h.$("new-email").value="researcher@example.org";h.$("new-title").value="RL test";await h.submitFor("new-email");assert.equal(h.calls.filter(c=>c.options.method).length,0);h.$("storage-accepted").checked=true;await h.submitFor("new-email");const request=h.calls.find(c=>c.url==="/api/lite/projects"&&c.options.method);assert.deepEqual(JSON.parse(request.options.body),{title:"RL test",organizer_email:"researcher@example.org",storage_accepted:true});assert.equal(h.url,"/lite?project=p1");});
test("Empty source import has no network side effect",async()=>{const h=harness();await flush();await h.click("sources-button");await h.submitFor("paper-url");assert.match(h.$("dialog-error").textContent,/Add a paper URL/);assert.ok(!h.calls.some(c=>c.url.endsWith("/import")));});
test("Source import includes paper, repository, and researcher brief",async()=>{const h=harness();await flush();await h.click("sources-button");h.$("paper-url").value="https://arxiv.org/abs/2006.13760";h.$("repository-url").value="https://github.com/NetHack-LE/nle";h.$("source-brief").value="Study long-horizon credit assignment.";await h.submitFor("paper-url");const data=JSON.parse(h.calls.find(c=>c.url.endsWith("/import")).options.body);assert.equal(data.paper_url,"https://arxiv.org/abs/2006.13760");assert.equal(data.repository_url,"https://github.com/NetHack-LE/nle");assert.equal(data.brief,"Study long-horizon credit assignment.");});
test("Cross-tab sign-out removes private content and keeps the resume URL",async()=>{const h=harness();await flush();h.events.storage({key:"autokaggle-session-ended"});assert.equal(h.$("messages").children.length,0);assert.equal(h.$("message-input").disabled,true);assert.equal(h.$("sign-in").href,"/login?next="+encodeURIComponent("/lite?project=p1"));});
test("Late queued responses cannot restore a signed-out session",async()=>{const h=harness();await flush();let release;h.handler=async url=>url.endsWith("/message")?new Promise(resolve=>release=resolve):null;await h.input("message-input","One A100 for six hours.");const pending=h.click("send-message");await flush();h.events.storage({key:"autokaggle-session-ended"});release({ok:true,json:async()=>fixture()});await pending;assert.equal(h.$("messages").children.length,0);assert.equal(h.$("message-input").disabled,true);});
test("An oversized paper is rejected before upload",async()=>{const h=harness();await flush();await h.click("sources-button");h.$("paper-file").files=[{name:"paper.pdf",size:16*1024*1024+1}];await h.submitFor("paper-url");assert.match(h.$("dialog-error").textContent,/16 MB or less/);assert.ok(!h.calls.some(c=>c.url.endsWith("/paper")));});
test("A login expiry clears both the open dialog and private messages",async()=>{const h=harness();await flush();await h.click("package-button");h.handler=async url=>url.endsWith("/build")?{ok:false,status:401,json:async()=>({detail:"Sign in required"})}:null;await h.clickText("Rebuild package");assert.equal(h.$("detail-dialog").open,false);assert.equal(h.$("dialog-content").children.length,0);assert.equal(h.$("messages").children.length,0);assert.equal(h.$("sign-in").hidden,false);});
test("Session resume keeps the Lite route and performs no create request",async()=>{const h=harness();await flush();await h.click("sessions-button");await h.clickText("Resume →");assert.equal(h.url,"/lite?project=p1");assert.equal(h.calls.filter(c=>c.options.method).length,0);});
test("Polling keeps recovering after more than one connection failure",async()=>{const f=fixture();f.status="working";const h=harness(f);await flush();h.handler=async url=>{if(url.endsWith("/lite"))throw new TypeError("Offline");};for(let i=0;i<2;i++){const timer=[...h.timers.values()].find(t=>t.ms===1500||t.ms===5000);assert.ok(timer);await timer.f();await flush();assert.ok([...h.timers.values()].some(t=>t.ms===5000));}assert.equal(h.$("refresh-session").disabled,false);});
test("Cross-tab sign-out clears saved local drafts and request payloads",async()=>{const h=harness();await flush();await h.input("message-input","Private unfinished text");assert.ok(h.storage.size);h.events.storage({key:"autokaggle-session-ended"});assert.equal(h.storage.size,0);});
test("Session deletion requires the explicit confirmation and removes the current view",async()=>{const h=harness();await flush();h.handler=async(url,options)=>url==="/api/lite/projects"?{ok:true,json:async()=>({projects:[{id:"p1",title:"Temporary test",can_delete:true}]})}:null;await h.click("sessions-button");await h.clickText("Delete");await h.submitFor("delete-confirm");assert.ok(!h.calls.some(c=>c.options.method==="DELETE"));h.$("delete-confirm").value="DELETE";await h.submitFor("delete-confirm");const deleted=h.calls.find(c=>c.options.method==="DELETE");assert.equal(deleted.url,"/api/projects/p1");assert.deepEqual(JSON.parse(deleted.options.body),{confirm:true});assert.equal(h.url,"/lite");assert.equal(h.$("messages").children.length,0);});
test("Partial extraction shows field notes and preserves the valid proposal",async()=>{const f=fixture();f.proposal={id:"proposal-3",contract:{objective:"Study ascension"},validation_notes:[{field:"answer_exposure",reason:"Choose visible, private, or environment_generated."}]};const h=harness(f);await flush();await h.click("review-proposals");assert.match(h.$("dialog-content").textContent,/Some proposed values need a decision/);assert.match(h.$("dialog-content").textContent,/Answer exposure/);assert.match(h.$("dialog-content").textContent,/Study ascension/);});

test("Challenge website results link opens the saved session result dialog",async()=>{const h=harness(fixture(),"?project=p1","#results");await flush();assert.equal(h.$("detail-dialog").open,true);assert.equal(h.$("dialog-title").textContent,"Results and evidence");assert.equal(h.calls.filter(c=>c.options.method).length,0);});

test("Current package has a direct config download",async()=>{const h=harness();await flush();await h.click("package-button");assert.match(h.$("dialog-content").textContent,/Download config/);});

test("An open decision can save defined details without claiming the definition is complete",async()=>{const f=fixture();f.ready=false;f.proposal={id:"proposal-open",summary:"Policy proposed",contract:{outputs:"Sampling rule remains to be confirmed"},open_decisions:[{field:"outputs",reason:"Choose the sampling distribution and random-number generator."}]};const h=harness(f);await flush();await h.click("review-proposals");assert.match(h.$("dialog-content").textContent,/Choose the sampling distribution and random-number generator/);assert.match(h.$("dialog-content").textContent,/before you can build the package/);assert.doesNotMatch(h.$("dialog-content").textContent,/Accept this definition/);await h.clickText("Save defined details");const call=h.calls.find(c=>c.url.endsWith("/accept"));assert.deepEqual(JSON.parse(call.options.body),{proposal_id:"proposal-open"});});

test("Checklist details show the reason a recorded field is still open",async()=>{const f=fixture();f.ready=false;f.checklist[1].resolved=6;f.checklist[1].missing=["metric"];f.checklist[1].open_decisions=[{field:"metric",reason:'Confirm whether <success> means reaching the goal.'}];const h=harness(f);await flush();await h.click("check-evaluation");const text=h.$("dialog-content").textContent;assert.match(text,/Confirm whether <success> means reaching the goal/);assert.match(text,/success_rate/);assert.match(text,/saved details remain available/);assert.equal(h.$("check-evaluation").attributes["aria-label"],"Evaluation: 6 of 7 details recorded");});

function evaluatorView(extra={}){return {status:"not_built",draft:true,available:true,unavailable_reason:"",contract:{accepted:true,version:"v1",package_status:"ready",title:"T"},release:null,latest:null,earlier_releases:[],builds:0,settings:{model:"openai/gpt-6.1-sol",effort:"medium",minutes:30,requests:150,runtime:"docker"},...extra};}
test("The evaluator dialog shows blockers and keeps an untested build a draft",async()=>{const h=harness();await flush();
 const view=evaluatorView({status:"blocked",latest:{status:"blocked",stage:"Waiting for a decision",cause:"A decision or input that affects scoring is missing.",blockers:[{field:"source_revision",reason:"Which label release should scoring use?"}],tests:[]}});
 h.handler=async url=>url.endsWith("/lite/evaluator")?{ok:true,status:200,json:async()=>structuredClone(view)}:null;
 await h.click("evaluator-button");const text=h.$("dialog-content").textContent;
 assert.match(text,/Draft · a decision is needed/);assert.match(text,/Source revision: Which label release should scoring use\?/);assert.doesNotMatch(text,/Download release/);assert.match(text,/Build evaluator/);});
test("Starting a build sends one request identity and polls the saved build",async()=>{const h=harness();await flush();let view=evaluatorView();
 h.handler=async(url,options)=>{if(url.endsWith("/lite/evaluator/build")){view=evaluatorView({status:"building",builds:1,latest:{status:"building",stage:"The coding agent is implementing and testing the evaluator",tests:[],blockers:[]}});}
  return url.includes("/lite/evaluator")?{ok:true,status:200,json:async()=>structuredClone(view)}:null;};
 await h.click("evaluator-button");await h.clickText("Build evaluator");const call=h.calls.find(c=>c.url.endsWith("/lite/evaluator/build"));
 assert.deepEqual(Object.keys(JSON.parse(call.options.body)),["request_id","feedback"]);assert.match(h.$("dialog-content").textContent,/Building/);
 await h.clickText("Build evaluator");assert.equal(h.calls.filter(c=>c.url.endsWith("/evaluator/build")).length,1);
 assert.ok([...h.timers.values()].some(t=>t.ms===3000));});
test("A ready evaluator shows the bound release, its measured fitness, and the scoring command",async()=>{const h=harness();await flush();
 const build={status:"ready",evaluator_version:2,contract_version:"v1",tests:[{name:"valid example",passed:true,detail:"Observed 1.0; expected 1.0."}],model:{agent:"opencode",name:"deepseek-v4-pro",provider:"DeepSeek",reasoning:"medium",requests:41},runtime:{kind:"docker"},
  evidence:{commit:"c".repeat(40),tag:"v2",fixture:"fixtures/valid/predictions.csv",expected_fitness:1,observed_fitness:1,command:"python evaluate.py --artifact fixtures/valid/predictions.csv"},
  bundle_url:"/api/projects/p1/lite/evaluator/bundle",config_url:"/api/projects/p1/lite/evaluator/config",readme_url:"/api/projects/p1/lite/evaluator/readme.md"};
 const view=evaluatorView({status:"ready",draft:false,release:build,builds:2,earlier_releases:[{evaluator_version:1,contract_version:"v0",commit:"a".repeat(40)}]});
 h.handler=async url=>url.endsWith("/lite/evaluator")?{ok:true,status:200,json:async()=>structuredClone(view)}:null;
 await h.click("evaluator-button");const text=h.$("dialog-content").textContent;
 assert.match(text,/Software release/);assert.match(text,/git checkout v2/);assert.match(text,/expected fitness 1/);assert.match(text,/Download release/);assert.match(text,/Rebuild evaluator/);assert.match(text,/version 1 \(contract v0\)/);assert.match(text,/with deepseek-v4-pro on DeepSeek/);});
test("A tested release is published on request and then shows its private repository",async()=>{const h=harness();await flush();
 const build={status:"ready",evaluator_version:1,contract_version:"v1",tests:[],published:null,evidence:{commit:"c".repeat(40),tag:"v1",fixture:"fixtures/valid/p.csv",expected_fitness:1,observed_fitness:1,command:"python evaluate.py --artifact fixtures/valid/p.csv"},
  bundle_url:"/api/projects/p1/lite/evaluator/bundle",config_url:"/api/projects/p1/lite/evaluator/config",readme_url:"/api/projects/p1/lite/evaluator/readme.md"};
 let view=evaluatorView({status:"ready",draft:false,release:build,builds:1,publishing:{available:true,reason:"",owner:"bold-test",repository:null}});
 h.handler=async(url,options)=>{if(url.endsWith("/lite/evaluator/publish")){assert.equal(options.method,"POST");view=evaluatorView({...view,release:{...build,published:{url:"https://github.com/bold-test/lite-eval-t-12345678",repository:"bold-test/lite-eval-t-12345678",tag:"v1",address_recorded:false}},publishing:{available:true,reason:"",owner:"bold-test",repository:{url:"https://github.com/bold-test/lite-eval-t-12345678",name:"bold-test/lite-eval-t-12345678"}}});}
  return url.includes("/lite/evaluator")?{ok:true,status:200,json:async()=>structuredClone(view)}:null;};
 await h.click("evaluator-button");let text=h.$("dialog-content").textContent;
 assert.match(text,/git clone evaluator\.bundle evaluator/);assert.match(text,/creates a private repository under bold-test/);
 await h.clickText("Publish to GitHub");text=h.$("dialog-content").textContent;
 assert.equal(h.calls.filter(c=>c.url.endsWith("/lite/evaluator/publish")).length,1);
 assert.match(text,/Published to the private GitHub repository bold-test\/lite-eval-t-12345678/);assert.match(text,/git clone https:\/\/github\.com\/bold-test\/lite-eval-t-12345678\.git evaluator/);
 assert.match(text,/lock file does not name this repository/);assert.doesNotMatch(text,/Publish again/);});
test("The evaluator dialog offers no publishing control when the server has none",async()=>{const h=harness();await flush();
 const build={status:"ready",evaluator_version:1,contract_version:"v1",tests:[],published:null,evidence:{commit:"c".repeat(40),tag:"v1",fixture:"f",expected_fitness:1,observed_fitness:1,command:"python evaluate.py --artifact f"},bundle_url:"/api/projects/p1/lite/evaluator/bundle",config_url:"/api/projects/p1/lite/evaluator/config",readme_url:"/api/projects/p1/lite/evaluator/readme.md"};
 const view=evaluatorView({status:"ready",draft:false,release:build,builds:1,publishing:{available:false,reason:"Publishing needs a GitHub login on this server. Sign in with gh, or provide GH_TOKEN.",owner:"bold-test",repository:null}});
 h.handler=async url=>url.endsWith("/lite/evaluator")?{ok:true,status:200,json:async()=>structuredClone(view)}:null;
 await h.click("evaluator-button");const text=h.$("dialog-content").textContent;
 assert.doesNotMatch(text,/Publish to GitHub/);assert.match(text,/Publishing needs a GitHub login on this server/);});
function blank(){const f=fixture();Object.assign(f,{title:"New internal experiment",messages:[{role:"assistant",content:"Start with the ML problem you want to study. You can add a paper and a GitHub repository."}],contract:{},ready:false,sources:[],proposal:null,stage:"",package:{status:"none"},model:{configured:true,calls:0,round_calls:0,limit:30}});return f;}
function answered(h,f){h.handler=async(url,options)=>{if(options?.method==="POST"&&/\/lite\/(import|message|paper|attachments)$/.test(url)){if(url.endsWith("/paper")||url.endsWith("/attachments"))f.sources=[{kind:"paper",url:"uploaded:paper.pdf",title:"paper.pdf"}];else f.messages=[...f.messages,{role:"user",content:"saved"},{role:"assistant",content:"Here is a proposed definition."}];return {ok:true,status:200,json:async()=>structuredClone(f)};}return null;};}
const posts=h=>h.calls.filter(c=>c.options?.method==="POST").map(c=>[c.url.split("/lite/")[1],typeof c.options.body==="string"?JSON.parse(c.options.body):"form"]);
test("A new session opens with the paper question in the conversation, not a dialog or a start button",async()=>{const f=blank(),h=harness(f);await flush();
 assert.match(h.$("messages").textContent,/Is this work based on a paper\?/);assert.doesNotMatch(h.$("messages").textContent,/code repository/);assert.doesNotMatch(h.$("messages").textContent,/You can add a paper/);
 assert.notEqual(h.$("detail-dialog").open,true);assert.equal(h.$("attach-paper").hidden,false);assert.match(h.$("message-input").placeholder,/Paste a link/);
 const html=fs.readFileSync(path.join(__dirname,"../static/lite.html"),"utf8"),tools=html.slice(html.indexOf('<footer class="conversation-tools">'),html.indexOf("</footer>"));
 assert.doesNotMatch(tools,/Paper & repository/);assert.match(html.slice(html.indexOf('id="message-form"'),html.indexOf("</form>")),/id="attach-paper"/);});
test("Paper, repository, and question are asked in order and sent as one import",async()=>{const f=blank(),h=harness(f);await flush();answered(h,f);
 await h.input("message-input","It is https://arxiv.org/abs/2006.13760.");await h.click("send-message");
 assert.match(h.$("messages").textContent,/Is there a code repository for it\?/);assert.equal(h.$("attach-paper").hidden,false);assert.equal(posts(h).length,0);
 await h.input("message-input","https://gitlab.com/group/project");await h.click("send-message");
 assert.match(h.$("messages").textContent,/I can read public GitHub repositories only/);assert.equal(posts(h).length,0);
 await h.input("message-input","Yes: https://github.com/NetHack-LE/nle");await h.click("send-message");
 assert.match(h.$("messages").textContent,/What do you want to investigate\?/);assert.equal(posts(h).length,0);
 await h.input("message-input","Study long-horizon credit assignment.");await h.click("send-message");
 assert.deepEqual(posts(h).map(([tail,body])=>[tail,body.paper_url,body.repository_url,body.brief]),[["import","https://arxiv.org/abs/2006.13760","https://github.com/NetHack-LE/nle","Study long-horizon credit assignment."]]);
 assert.match(h.$("messages").textContent,/Here is a proposed definition/);assert.doesNotMatch(h.$("messages").textContent,/Is this work based on a paper/);assert.equal([...h.storage.keys()].some(k=>k.includes("intake")),false);});
test("Without a paper or repository the research question is sent as an ordinary message",async()=>{const f=blank(),h=harness(f);await flush();answered(h,f);
 await h.input("message-input","No, there is no paper yet.");await h.click("send-message");assert.match(h.$("messages").textContent,/Is there a code repository/);
 await h.input("message-input","none");await h.click("send-message");assert.match(h.$("messages").textContent,/What do you want to investigate/);
 await h.input("message-input","Does curriculum order change sample efficiency?");await h.click("send-message");
 assert.deepEqual(posts(h),[["message",{message:"Does curriculum order change sample efficiency?",request_id:posts(h)[0][1].request_id}]]);});
test("Both links in one reply skip the repository question, and a long first reply becomes the research question",async()=>{const f=blank(),h=harness(f);await flush();answered(h,f);
 await h.input("message-input","I want to test whether intrinsic rewards help exploration in sparse-reward navigation tasks.");await h.click("send-message");
 assert.match(h.$("messages").textContent,/I will use that as your research question\. Is this work based on a paper\?/);
 await h.input("message-input","Paper https://arxiv.org/abs/1810.12894, code https://github.com/openai/random-network-distillation.");await h.click("send-message");
 assert.deepEqual(posts(h).map(([tail,body])=>[tail,body.paper_url,body.repository_url,/intrinsic rewards/.test(body.brief)]),[["import","https://arxiv.org/abs/1810.12894","https://github.com/openai/random-network-distillation",true]]);});
test("Attachments are queued, removable, and uploaded before the source import",async()=>{const f=blank(),h=harness(f);await flush();answered(h,f);
 h.$("paper-attach").files=[{name:"notes.txt",size:10},{name:"paper.pdf",size:2048}];await h.$("paper-attach").events.change();await flush();
 assert.match(h.$("attachment-list").textContent,/notes.txt/);assert.match(h.$("attachment-list").textContent,/paper.pdf/);assert.equal(posts(h).length,0);
 await h.click("send-message");assert.match(h.$("messages").textContent,/Attached notes.txt, paper.pdf/);assert.match(h.$("messages").textContent,/Is there a code repository/);
 await h.input("message-input","no repository");await h.click("send-message");await h.input("message-input","Reproduce table 2.");await h.click("send-message");
 assert.deepEqual(posts(h).map(([tail])=>tail),["attachments","attachments","import"]);
});
test("Attachments can be sent in an existing session without text",async()=>{const h=harness();await flush();
 h.$("paper-attach").files=[{name:"notes.csv",size:64}];await h.$("paper-attach").events.change();await h.click("send-message");
 assert.deepEqual(posts(h).map(([tail])=>tail),["attachments","message"]);
 assert.match(posts(h)[1][1].message,/read the attached files/);
});
test("Opening answers survive a reload, and a failed first request asks again",async()=>{const f=blank(),h=harness(f);await flush();
 await h.input("message-input","https://arxiv.org/abs/2006.13760");await h.click("send-message");
 const saved=[...h.storage.entries()].find(([k])=>k.includes("intake"));assert.ok(saved);assert.equal(JSON.parse(saved[1]).paper,"https://arxiv.org/abs/2006.13760");assert.equal("file" in JSON.parse(saved[1]),false);
 h.handler=async(url,options)=>options?.method==="POST"&&url.endsWith("/import")?{ok:false,status:422,json:async()=>({detail:"Use a public GitHub repository link."})}:null;
 await h.input("message-input","https://github.com/owner/missing");await h.click("send-message");await h.input("message-input","A question.");await h.click("send-message");
 assert.match(h.$("messages").textContent,/That did not go through\. Check the links\. Is this work based on a paper\?/);assert.equal(h.$("attach-paper").hidden,false);});
test("A saved session with messages does not show the opening questions",async()=>{const h=harness();await flush();assert.doesNotMatch(h.$("messages").textContent,/Is this work based on a paper/);assert.equal(h.$("attach-paper").hidden,false);
 await h.input("message-input","A correction.");await h.click("send-message");assert.deepEqual(posts(h).map(p=>p[0]),["message"]);});

 test("Automatic publication keeps polling and offers retry and a pinned ZIP",async()=>{const h=harness();await flush();
 const release={status:"ready",evaluator_version:1,tests:[],publication:{status:"publishing"},published:null,
 evidence:{commit:"c".repeat(40),tag:"v1",fixture:"f",expected_fitness:1,observed_fitness:1,command:"python evaluate.py --artifact f"},
 bundle_url:"/api/projects/p1/lite/evaluator/bundle",config_url:"/api/projects/p1/lite/evaluator/config",readme_url:"/api/projects/p1/lite/evaluator/readme.md"};
 let view=evaluatorView({status:"ready",draft:false,release,publishing:{automatic:true,available:true,owner:"bold-test"}});
 h.handler=async(url,options)=>{if(url.endsWith("/evaluator/publish"))view={...view,release:{...release,publication:{status:"published"},published:{url:"https://github.com/bold-test/eval",zip_url:"https://github.com/bold-test/eval/archive/"+"c".repeat(40)+".zip",repository:"bold-test/eval",tag:"v1",address_recorded:true}}};return url.includes("/lite/evaluator")?{ok:true,status:200,json:async()=>structuredClone(view)}:null;};
 await h.click("evaluator-button");assert.match(h.$("dialog-content").textContent,/Publishing the tested evaluator/);
 assert.ok([...h.timers.values()].some(t=>t.ms===3000));
 await h.clickText("Rebuild evaluator");assert.equal(h.calls.filter(c=>c.url.endsWith("/evaluator/build")).length,0);
 view={...view,release:{...release,publication:{status:"failed",error:"The service restarted."}}};
 await h.click("evaluator-button");assert.match(h.$("dialog-content").textContent,/Retry publication/);
 await h.clickText("Retry publication");assert.match(h.$("dialog-content").textContent,/Download GitHub ZIP/);
 assert.doesNotMatch(h.$("dialog-content").textContent,/Retry publication/);
 });
test("GitHub links inside a repository stay in the chat message; only repository roots are imported",async()=>{const h=harness();await flush();
 const archive="Compare with https://github.com/owner/repo/archive/0123456789abcdef0123456789abcdef01234567.tar.gz please.";
 await h.input("message-input",archive);await h.click("send-message");
 await h.input("message-input","See https://github.com/owner/repo/blob/main/train.py#L10");await h.click("send-message");
 await h.input("message-input","Code is at https://github.com/owner/repo/.");await h.click("send-message");
 const sent=posts(h);assert.deepEqual(sent.map(p=>p[0]),["message","message","import"]);
 assert.equal(sent[0][1].message,archive);assert.equal(sent[2][1].repository_url,"https://github.com/owner/repo/");});
test("Opening questions ask for the repository root when given a link inside a repository",async()=>{const f=blank(),h=harness(f);await flush();answered(h,f);
 await h.input("message-input","https://github.com/owner/repo/archive/0123456789abcdef0123456789abcdef01234567.tar.gz");await h.click("send-message");
 assert.match(h.$("messages").textContent,/points inside a repository\. Paste the repository's main link/);assert.match(h.$("messages").textContent,/Is this work based on a paper\?/);
 await h.input("message-input","No paper.");await h.click("send-message");assert.match(h.$("messages").textContent,/Is there a code repository/);
 await h.input("message-input","https://github.com/owner/repo/tree/main/src");await h.click("send-message");
 assert.match(h.$("messages").textContent,/points inside a repository/);assert.equal(posts(h).length,0);
 await h.input("message-input","https://github.com/owner/repo");await h.click("send-message");
 await h.input("message-input","Reproduce the baseline.");await h.click("send-message");
 assert.deepEqual(posts(h).map(([tail,body])=>[tail,body.paper_url,body.repository_url,body.brief]),[["import","","https://github.com/owner/repo","Reproduce the baseline."]]);});
function reviewedRelease(extra={}) { return {id:'b1',status:'ready',evaluator_version:1,tests:[],
 evidence:{commit:'c'.repeat(40),tag:'v1',fixture:'fixtures/valid.csv',expected_fitness:1,observed_fitness:1,command:'python evaluate.py --mode synthetic --artifact fixtures/valid.csv'},
 validation:{contract_coverage:'passed',code_review:'passed',synthetic:'passed',research_data:'not_run'},...extra}; }
test('Coding feedback uses the build route and preserves the saved review mode',async()=>{
 const h=harness();await flush();const release=reviewedRelease();
 h.handler=async url=>url.includes('/lite/evaluator')?{ok:true,status:200,json:async()=>evaluatorView({status:'ready',release})}:null;
 await h.click('evaluator-button');await h.clickText('Revise code in chat');
 await h.input('message-input','Save the diagnostic output as required by the contract.');await h.click('send-message');
 const call=h.calls.find(c=>c.url.endsWith('/evaluator/build'));
 assert.equal(JSON.parse(call.options.body).feedback,'Save the diagnostic output as required by the contract.');
 assert.equal(h.storage.get('autokaggle-lite-code-review:p1'),'yes');
 assert.ok(!h.calls.some(c=>c.url.endsWith('/lite/message')));
});
test('Research validation and human approval are distinct from a software release',async()=>{
 const h=harness();await flush();let release=reviewedRelease();
 h.handler=async url=>url.includes('/lite/evaluator')?{ok:true,status:200,json:async()=>evaluatorView({status:'ready',release})}:null;
 await h.click('evaluator-button');assert.match(h.$('dialog-content').textContent,/Declared research data: Not run/);
 assert.doesNotMatch(h.$('dialog-content').textContent,/Review and approve this version/);
 release=reviewedRelease({validation:{contract_coverage:'passed',code_review:'passed',synthetic:'passed',research_data:'validated',research_evidence:{report_sha256:'d'.repeat(64),expected_fitness:1,observed_fitness:1,expected_basis:'Independent result'}}});
 await h.click('evaluator-button');assert.match(h.$('dialog-content').textContent,/Download research validation/);
 await h.clickText('Review and approve this version');
 assert.match(h.$('dialog-content').textContent,/exact|commit and research report/);
 assert.ok(!h.calls.some(c=>c.url.endsWith('/evaluator/approve')));
});
test('A queued review email keeps the evaluator polling',async()=>{
 const h=harness();await flush();const release=reviewedRelease({review_invitation:{status:'queued'}});
 h.handler=async url=>url.includes('/lite/evaluator')?{ok:true,status:200,json:async()=>evaluatorView({status:'ready',release})}:null;
 await h.click('evaluator-button');assert.match(h.$('dialog-content').textContent,/Build review email: Queued/);
 assert.ok([...h.timers.values()].some(t=>t.ms===3000));
});

test("Handoff deep link checks access before offering a code",async()=>{
 const h=harness(fixture(),"?project=p1&review=handoff");
 h.handler=async url=>url.endsWith('/handoff')?{ok:true,status:200,json:async()=>({can_manage:false,members:[]})}:null;
 await flush();assert.match(h.$('dialog-content').textContent,/Only the session owner/);assert.equal(h.calls.filter(c=>c.options.method).length,0);
});
test("Owner must click to issue a handoff and can revoke it",async()=>{
 const h=harness(fixture(),"?project=p1&review=handoff");
 h.handler=async(url,options)=>url.includes('/handoff')?{ok:true,status:200,json:async()=>options.method==='POST'?{code:'TEST-ONLY',expires_at:'2026-11-14T00:00:00Z'}:{can_manage:true,members:[]}}:null;
 await flush();assert.equal(h.calls.filter(c=>c.options.method).length,0);
 await h.clickText('Create handoff code');assert.match(h.$('dialog-content').textContent,/TEST-ONLY/);
 await h.clickText('Revoke unused code');assert.match(h.$('dialog-content').textContent,/Unused codes revoked/);
});
test("Redeeming a handoff requires explicit consent and sends the supported API field",async()=>{
 const h=harness();await flush();await h.click('sessions-button');
 await h.input('handoff-redeem','TEST-ONLY');await h.submitFor('handoff-redeem');
 assert.equal(h.calls.some(c=>c.url==='/api/handoffs/redeem'),false);
 h.$('handoff-consent').checked=true;await h.submitFor('handoff-redeem');
 assert.deepEqual(JSON.parse(h.calls.find(c=>c.url==='/api/handoffs/redeem').options.body),{code:'TEST-ONLY',accepted:true});
});

test("Project links stay in the brief and are not imported as papers",async()=>{
 const f=blank(),h=harness(f);await flush();answered(h,f);
 await h.input("message-input","No paper. Project https://bold-lab-ai.github.io/bold-os/project.html#id=diverging-runs");await h.click("send-message");
 await h.input("message-input","No repository");await h.click("send-message");
 assert.match(h.$("messages").textContent,/Which BOLD OS project/);
 await h.input("message-input","Test a deterministic objective.");await h.click("send-message");
 const sent=posts(h);assert.equal(sent.length,1);assert.equal(sent[0][0],"message");assert.match(sent[0][1].message,/#id=diverging-runs/);
});

test('Handoff creation blocks concurrent revocation until it finishes',async()=>{
 const h=harness(fixture(),'?project=p1&review=handoff');let finish;
 h.handler=async(url,options)=>{
  if(!url.includes('/handoff'))return null;
  if(options.method==='POST')await new Promise(resolve=>{finish=resolve;});
  return {ok:true,status:200,json:async()=>options.method==='POST'?{code:'TEST-ONLY',expires_at:'2026-11-14T00:00:00Z'}:{can_manage:true,members:[]}};
 };
 await flush();const creating=h.clickText('Create handoff code');await flush();
 await h.clickText('Revoke unused code');assert.equal(h.calls.filter(c=>c.options.method==='DELETE').length,0);
 finish();await creating;await h.clickText('Revoke unused code');assert.equal(h.calls.filter(c=>c.options.method==='DELETE').length,1);
});
