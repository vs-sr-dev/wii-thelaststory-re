#!/usr/bin/env python3
"""
build_dialogue_browser.py - Genera un browser HTML locale testo+voce.

Legge dialogue_db/voiced_lines.tsv e produce dialogue_voice_browser.html nella
root del progetto (cosi' i path audio 'audio/vo/*.ogg' sono relativi e riproducibili
direttamente aprendo il file nel browser).

Funzioni: filtro testo full-text, selezione scena e personaggio, toggle lingua,
play inline della clip vocale, durata. Dati embeddati come JSON (nessuna fetch,
funziona da file://).
"""
import os, csv, json, html

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB   = os.path.join(ROOT, 'dialogue_db')
OUT  = os.path.join(ROOT, 'dialogue_voice_browser.html')

LANGS = ['jp', 'en', 'fr', 'de', 'es', 'it']
LANGNAME = {'jp':'日本語','en':'English','fr':'Français','de':'Deutsch','es':'Español','it':'Italiano'}

def main():
    rows = []
    with open(os.path.join(DB, 'voiced_lines.tsv'), encoding='utf-8', newline='') as fh:
        for r in csv.DictReader(fh, delimiter='\t'):
            rows.append({
                's': r['scene'],
                'c': r['chara'],
                'v': r['voice'],
                'o': r['ogg'],          # path OGG relativo (vo/ o se/), '' se assente
                'd': r['seconds'],
                'sr': r['sample_rate'],
                'ch': r['channels'],
                'hs': r['has_stream'],
                't': [r['jp'], r['en'], r['fr'], r['de'], r['es'], r['it']],
            })
    scenes = sorted(set(r['s'] for r in rows))
    charas = sorted(set(r['c'] for r in rows if r['c']))
    data = json.dumps(rows, ensure_ascii=False, separators=(',', ':'))

    page = HTML_TEMPLATE.replace('/*DATA*/', data) \
        .replace('/*SCENES*/', json.dumps(scenes, ensure_ascii=False)) \
        .replace('/*CHARAS*/', json.dumps(charas, ensure_ascii=False)) \
        .replace('/*NROWS*/', str(len(rows)))
    with open(OUT, 'w', encoding='utf-8') as fh:
        fh.write(page)
    print(f"scritto {OUT}")
    print(f"  {len(rows)} battute doppiate, {len(scenes)} scene, {len(charas)} personaggi")
    print(f"  apri il file nel browser (Firefox consigliato per l'audio da file://)")

HTML_TEMPLATE = r"""<!doctype html>
<html lang="it"><head><meta charset="utf-8">
<title>The Last Story — Dialoghi &amp; Voci</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root{--bg:#12141a;--panel:#1b1e27;--line:#272b38;--fg:#e6e8ee;--mut:#8a90a2;--acc:#c9a24b;--acc2:#5a7fb5}
  *{box-sizing:border-box}
  body{margin:0;font:14px/1.5 "Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--fg)}
  header{position:sticky;top:0;z-index:10;background:linear-gradient(180deg,#1b1e27,#171922);
    border-bottom:1px solid var(--line);padding:12px 16px}
  h1{margin:0 0 8px;font-size:18px;font-weight:600;letter-spacing:.3px}
  h1 span{color:var(--acc)}
  .controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
  input,select{background:#0e1016;border:1px solid var(--line);color:var(--fg);
    border-radius:6px;padding:6px 9px;font-size:13px}
  input#q{flex:1;min-width:200px}
  .lang-toggle{display:flex;gap:4px;flex-wrap:wrap}
  .lang-toggle button{background:#0e1016;border:1px solid var(--line);color:var(--mut);
    border-radius:5px;padding:4px 8px;font-size:12px;cursor:pointer}
  .lang-toggle button.on{background:var(--acc2);border-color:var(--acc2);color:#fff}
  .stat{color:var(--mut);font-size:12px;margin-left:auto}
  main{padding:8px 16px 60px}
  .row{border:1px solid var(--line);border-radius:8px;margin:8px 0;background:var(--panel);overflow:hidden}
  .rhead{display:flex;align-items:center;gap:10px;padding:8px 12px;background:#20242f;flex-wrap:wrap}
  .play{background:var(--acc);border:0;color:#1a1300;width:34px;height:34px;border-radius:50%;
    font-size:14px;cursor:pointer;flex:0 0 auto;display:flex;align-items:center;justify-content:center}
  .play:disabled{background:#3a3d48;color:#6a6d78;cursor:not-allowed}
  .play.playing{background:var(--acc2);color:#fff}
  .chara{font-weight:600;color:var(--acc)}
  .meta{color:var(--mut);font-size:12px;font-family:ui-monospace,monospace}
  .rbody{padding:6px 12px 10px}
  .l{display:flex;gap:8px;padding:2px 0;border-top:1px solid #21242f}
  .l:first-child{border-top:0}
  .lc{flex:0 0 34px;color:var(--mut);font-size:11px;text-transform:uppercase;padding-top:2px}
  .lt{flex:1;white-space:pre-wrap;word-break:break-word}
  .nostream{color:#c96b6b;font-size:11px}
  mark{background:var(--acc);color:#1a1300;border-radius:2px}
  #more{display:block;margin:16px auto;padding:8px 20px;background:var(--panel);
    border:1px solid var(--line);color:var(--fg);border-radius:8px;cursor:pointer}
  .empty{text-align:center;color:var(--mut);padding:40px}
</style></head>
<body>
<header>
  <h1>The Last Story — Dialoghi <span>&amp;</span> Voci &nbsp;<span style="color:#8a90a2;font-weight:400;font-size:13px">testo↔voce affiancati · /*NROWS*/ battute doppiate</span></h1>
  <div class="controls">
    <input id="q" placeholder="cerca nel testo (tutte le lingue) o nel voiceID…" autocomplete="off">
    <select id="scene"><option value="">— tutte le scene —</option></select>
    <select id="chara"><option value="">— tutti i personaggi —</option></select>
    <div class="lang-toggle" id="langs"></div>
    <span class="stat" id="stat"></span>
  </div>
</header>
<main id="list"></main>
<audio id="player"></audio>
<script>
const DATA = /*DATA*/;
const SCENES = /*SCENES*/;
const CHARAS = /*CHARAS*/;
const LANGS = ["jp","en","fr","de","es","it"];
const LANGNAME = {jp:"JP",en:"EN",fr:"FR",de:"DE",es:"ES",it:"IT"};
const PAGE = 60;
let shown = PAGE, activeLangs = new Set(["jp","en","it"]);

const $ = s => document.querySelector(s);
const listEl = $("#list"), player = $("#player");
let curBtn = null;

// popola select
for(const s of SCENES){const o=document.createElement("option");o.value=s;o.textContent=s;$("#scene").appendChild(o);}
for(const c of CHARAS){const o=document.createElement("option");o.value=c;o.textContent=c;$("#chara").appendChild(o);}
// toggle lingue
const lt=$("#langs");
for(const l of LANGS){const b=document.createElement("button");b.textContent=LANGNAME[l];
  if(activeLangs.has(l))b.classList.add("on");
  b.onclick=()=>{activeLangs.has(l)?activeLangs.delete(l):activeLangs.add(l);b.classList.toggle("on");render();};
  lt.appendChild(b);}

function esc(s){return (s||"").replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));}
function hl(s,q){s=esc(s);if(!q)return s;
  try{return s.replace(new RegExp("("+q.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")+")","ig"),"<mark>$1</mark>");}catch(e){return s;}}

function filtered(){
  const q=$("#q").value.trim().toLowerCase();
  const sc=$("#scene").value, ch=$("#chara").value;
  return DATA.filter(r=>{
    if(sc&&r.s!==sc)return false;
    if(ch&&r.c!==ch)return false;
    if(q){const hay=(r.v+" "+r.t.join(" ")).toLowerCase();if(!hay.includes(q))return false;}
    return true;
  });
}

function play(src,btn){
  if(curBtn===btn && !player.paused){player.pause();return;}
  if(curBtn)curBtn.classList.remove("playing");
  player.src=src;
  player.play().then(()=>{btn.classList.add("playing");curBtn=btn;})
    .catch(()=>{btn.classList.remove("playing");btn.title="clip non disponibile";});
}
player.onended=()=>{if(curBtn)curBtn.classList.remove("playing");curBtn=null;};
player.onpause=()=>{if(curBtn)curBtn.classList.remove("playing");};

function render(){
  const rows=filtered();
  const q=$("#q").value.trim();
  $("#stat").textContent=rows.length+" battute";
  listEl.innerHTML="";
  if(!rows.length){listEl.innerHTML='<div class="empty">nessun risultato</div>';return;}
  const frag=document.createDocumentFragment();
  for(const r of rows.slice(0,shown)){
    const row=document.createElement("div");row.className="row";
    const dur=r.d?(r.d+"s"):"";
    const streamBad=!r.o;
    row.innerHTML=
      '<div class="rhead">'+
        '<button class="play" '+(streamBad?'disabled':'')+' title="'+r.v+'">▶</button>'+
        '<span class="chara">'+esc(r.c||"—")+'</span>'+
        '<span class="meta">'+r.s+' · '+r.v+(dur?' · '+dur:'')+(r.sr?' · '+r.sr+'Hz':'')+'</span>'+
        (streamBad?'<span class="nostream">SFX nel brsar (no stream)</span>':'')+
      '</div>'+
      '<div class="rbody">'+
        LANGS.filter(l=>activeLangs.has(l)).map((l,i)=>{
          const idx=LANGS.indexOf(l);const txt=r.t[idx];
          if(!txt)return"";
          return '<div class="l"><div class="lc">'+LANGNAME[l]+'</div><div class="lt">'+hl(txt,q)+'</div></div>';
        }).join("")+
      '</div>';
    const btn=row.querySelector(".play");
    if(!streamBad)btn.onclick=()=>play(r.o,btn);
    frag.appendChild(row);
  }
  listEl.appendChild(frag);
  if(rows.length>shown){
    const b=document.createElement("button");b.id="more";
    b.textContent="mostra altre "+Math.min(PAGE,rows.length-shown)+" (di "+(rows.length-shown)+" rimanenti)";
    b.onclick=()=>{shown+=PAGE;render();};
    listEl.appendChild(b);
  }
}
for(const id of ["#q","#scene","#chara"])$(id).addEventListener("input",()=>{shown=PAGE;render();});
render();
</script>
</body></html>
"""

if __name__ == '__main__':
    main()
