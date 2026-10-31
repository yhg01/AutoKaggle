"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../static/interface-switch.js"), "utf8");
const flush = () => new Promise(resolve => setImmediate(resolve));

function harness(url, access, open = [], stored = {}) {
  const current = new URL(url, "https://testserver"), destinations = [], requests = [], listeners = {};
  const links = ["intake", "internal"].map(kind => ({dataset: {interface: kind}, attributes: {}, events: {}, setAttribute(k,v) {this.attributes[k]=v;}, addEventListener(k,fn) {this.events[k]=fn;}}));
  const nav = {hidden: true, attributes: {}, querySelectorAll: () => links, setAttribute(k,v) {this.attributes[k]=v;}, removeAttribute(k) {delete this.attributes[k];}};
  const values = {...stored};
  const location = {origin: current.origin, pathname: current.pathname, search: current.search, href: current.href, assign: value => destinations.push(value)};
  const sessionStorage = {getItem: k => values[k] || null, setItem: (k,v) => {values[k]=v;}, removeItem: k => {delete values[k];}};
  const fetch = async url => {requests.push(url); if(url==="/api/access") {if(access instanceof Error) throw access; return {ok:true,json:async()=>access};} return {ok:open.includes(decodeURIComponent(url.split("/").at(-1)))};};
  vm.runInNewContext(source, {document:{getElementById:()=>nav}, window:{addEventListener:(k,v)=>{listeners[k]=v;}}, location, sessionStorage, URL, URLSearchParams, AbortSignal, fetch});
  return {nav, links, values, destinations, requests, listeners, async click(kind) {await links.find(l=>l.dataset.interface===kind).events.click({button:0,preventDefault(){}});}};
}

test("ordinary accounts never receive the Internal switch", async () => {
  const h=harness("/",{auth_kind:"user",is_admin:false}); await flush();
  assert.equal(h.nav.hidden,true); await h.click("internal"); assert.equal(h.destinations.length,0);
});
test("email accounts with explicit admin elevation receive both interfaces", async () => {
  const h=harness("/?project=own",{auth_kind:"user",is_admin:true}); await flush();
  assert.equal(h.nav.hidden,false); assert.equal(h.links[0].attributes["aria-current"],"page");
  await h.click("internal"); assert.equal(h.destinations[0],"/internal?project=own");
});
test("Internal returns to the same permitted project and preserves authentication", async () => {
  const h=harness("/internal?project=own&view=fields&record=submissions",{is_admin:true},["own"]); await flush();
  await h.click("intake"); assert.equal(h.destinations[0],"/?project=own");
  assert.equal(h.values["autokaggle-interface-context:internal"],"/internal?project=own&view=fields&record=submissions");
  assert.ok(h.requests.every(p=>p==="/api/access"||p.startsWith("/api/projects/")));
});
test("cross-account internal inspection returns to the user's permitted intake context", async () => {
  const h=harness("/internal?project=other",{is_admin:true},["own"],{"autokaggle-interface-context:intake":"/?project=own&view=review"}); await flush();
  await h.click("intake"); assert.equal(h.destinations[0],"/?project=own&view=review");
});
test("inaccessible or external saved contexts cannot open another account or origin", async () => {
  for(const context of ["https://other.example.org/?project=own","/?project=another","/login?project=own"]) {
    const h=harness("/internal?project=other",{is_admin:true},[],{"autokaggle-interface-context:intake":context}); await flush();
    await h.click("intake"); assert.equal(h.destinations[0],"/");
  }
});
test("returning to Internal preserves its review view for the same project", async () => {
  const h=harness("/?project=own",{is_admin:true},[],{"autokaggle-interface-context:internal":"/internal?project=own&view=calls&record=call-1"}); await flush();
  await h.click("internal"); assert.equal(h.destinations[0],"/internal?project=own&view=calls&record=call-1");
});
test("remembered contexts omit unrelated query parameters", async () => {
  const h=harness("/internal?project=own&view=fields&token=never-store-this",{is_admin:true},["own"]); await flush();
  await h.click("intake"); assert.ok(!h.values["autokaggle-interface-context:internal"].includes("token"));
});
test("access failures and cross-tab sign-out hide privileged navigation", async () => {
  const failed=harness("/",new Error("offline")); await flush(); assert.equal(failed.nav.hidden,true);
  const h=harness("/",{is_admin:true}); await flush(); assert.equal(h.nav.hidden,false);
  h.listeners.storage({key:"autokaggle-session-ended"}); assert.equal(h.nav.hidden,true);
  await h.click("internal"); assert.equal(h.destinations.length,0);
});
