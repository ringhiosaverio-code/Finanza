"""Report HTML di finanza.py: un file unico, senza dipendenze esterne, chiaro e scuro.

Mostra il ventaglio dei prezzi della Macchina del Tempo, le probabilità di uscita,
lo storico reale della stessa regola, l'eventuale tabella dell'ottimizzatore e il
verdetto di trader-risk. Si apre con un doppio clic: trader/report.html.
"""

import html
import json

STYLE = r"""
:root{color-scheme:light;
 --page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
 --grid:#e1e0d9;--axis:#c3c2b7;--neutral:#c3c2b7;
 --band-out:#cde2fb;--band-in:#86b6ef;--median:#184f95;
 --pos:#2a78d6;--neg:#eb6834;
 --good:#0ca30c;--critical:#d03b3b;--warning:#fab219;--good-ink:#006300;--crit-ink:#b02a2a;
 --chosen:#eef4fc;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;
 --page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;
 --grid:#2c2c2a;--axis:#383835;--neutral:#5a5955;
 --band-out:#104281;--band-in:#1c5cab;--median:#b7d3f6;
 --pos:#3987e5;--neg:#d95926;--good-ink:#0ca30c;--crit-ink:#e66767;--chosen:#1d2a3a;}}
:root[data-theme="dark"]{color-scheme:dark;
 --page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;
 --grid:#2c2c2a;--axis:#383835;--neutral:#5a5955;
 --band-out:#104281;--band-in:#1c5cab;--median:#b7d3f6;
 --pos:#3987e5;--neg:#d95926;--good-ink:#0ca30c;--crit-ink:#e66767;--chosen:#1d2a3a;}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);
 font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;font-variant-numeric:tabular-nums}
main{max-width:980px;margin:0 auto;padding:28px 16px 48px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:17px;margin:0 0 4px}
.sub{color:var(--ink2);margin:0}
.card{background:var(--surface);border:1px solid var(--grid);border-radius:12px;padding:18px 20px;margin-top:16px}
.note{color:var(--muted);font-size:13px;margin:6px 0 0}
.verdict{display:flex;gap:12px;align-items:flex-start;margin-top:18px;padding:14px 18px;border-radius:12px;
 background:var(--surface);border:1px solid var(--grid);border-left:5px solid var(--vc)}
.verdict .ic{flex:none;width:26px;height:26px;border-radius:50%;background:var(--vc);color:#fff;
 display:grid;place-items:center;font-weight:700}
.verdict.warn .ic{color:#0b0b0b}
.verdict b{font-size:16px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:16px}
.tile{background:var(--surface);border:1px solid var(--grid);border-radius:12px;padding:14px 16px}
.tile .k{color:var(--ink2);font-size:13px}
.tile .v{font-size:28px;font-weight:650;letter-spacing:-.02em;line-height:1.2}
.tile .d{color:var(--muted);font-size:12px}
.chart{position:relative;margin-top:10px}
.chart svg{display:block;width:100%;overflow:visible}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:13px;color:var(--ink2);margin-top:8px}
.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.legend i.line{height:2px;border-radius:1px;vertical-align:3px}
.tip{position:absolute;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--axis);
 border-radius:8px;padding:8px 10px;font-size:12.5px;box-shadow:0 4px 14px rgba(0,0,0,.12);display:none;white-space:nowrap;z-index:2}
.tip .t{font-weight:650;margin-bottom:2px}
.tip .r{display:flex;justify-content:space-between;gap:14px;color:var(--ink2)}
.tip .r span:last-child{color:var(--ink)}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{text-align:right;padding:7px 8px;white-space:nowrap;border-bottom:1px solid var(--grid)}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}
th{color:var(--ink2);font-weight:600}
tr.chosen td{background:var(--chosen);font-weight:600}
.scroll{overflow-x:auto}
.pos{color:var(--good-ink)}.neg{color:var(--crit-ink)}
.ticket{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-top:10px}
.ticket>div{border:1px solid var(--grid);border-radius:8px;padding:8px 12px}
.ticket .k{color:var(--ink2);font-size:12px}.ticket .v{font-size:17px;font-weight:600}
ul.reasons{margin:8px 0 0;padding-left:20px;color:var(--ink2)}
details summary{cursor:pointer;color:var(--ink2);font-size:13.5px;margin-top:10px}
footer{color:var(--muted);font-size:12.5px;margin-top:24px}
"""

SCRIPT = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmt = (x, d=2) => Number(x).toLocaleString('it-IT', {minimumFractionDigits:d, maximumFractionDigits:d});
const NS = 'http://www.w3.org/2000/svg';
function el(tag, attrs, parent){const e=document.createElementNS(NS,tag);for(const k in attrs)e.setAttribute(k,attrs[k]);if(parent)parent.appendChild(e);return e;}
function tip(box, html, x, y){const t=box.querySelector('.tip');t.innerHTML=html;t.style.display='block';
  const w=t.offsetWidth, W=box.clientWidth; t.style.left=Math.max(0,Math.min(W-w, x+14))+'px'; t.style.top=Math.max(0,y-10)+'px';}
function untip(box){box.querySelector('.tip').style.display='none';}

function fan(){
  const box=document.getElementById('fan'); if(!box||!D.bands) return;
  box.querySelector('svg')?.remove();
  const W=box.clientWidth, H=Math.max(260, Math.min(380, W*0.48)), m={l:48,r:10,t:18,b:28};
  const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,height:H,role:'img','aria-label':'Ventaglio dei prezzi simulati'});
  box.prepend(svg);
  const B=D.bands, n=B.length, P=D.plan;
  let lo=Math.min(...B.map(b=>b[0]),P.stop), hi=Math.max(...B.map(b=>b[4]),P.target);
  const pad=(hi-lo)*0.06; lo-=pad; hi+=pad;
  const x=i=>m.l+(W-m.l-m.r)*i/(n-1), y=v=>m.t+(H-m.t-m.b)*(hi-v)/(hi-lo);
  // griglia e asse y
  const step=niceStep((hi-lo)/5);
  for(let v=Math.ceil(lo/step)*step; v<=hi; v+=step){
    el('line',{x1:m.l,x2:W-m.r,y1:y(v),y2:y(v),stroke:css('--grid'),'stroke-width':1},svg);
    const t=el('text',{x:m.l-8,y:y(v)+4,'text-anchor':'end','font-size':11,fill:css('--muted')},svg); t.textContent=fmt(v, step<1?2:0);
  }
  // asse x: ogni ora
  let lastX=-1e9; const minGap=W<520?64:44;
  D.times.forEach((t,i)=>{ if((t.endsWith(':00')||i===0) && x(i)-lastX>=minGap && x(n-1)-x(i)>=minGap*0.6 || i===n-1){
    const tx=el('text',{x:x(i),y:H-8,'text-anchor':i===0?'start':(i===n-1?'end':'middle'),'font-size':11,fill:css('--muted')},svg); tx.textContent=t; lastX=x(i);}});
  el('line',{x1:m.l,x2:W-m.r,y1:H-m.b,y2:H-m.b,stroke:css('--axis'),'stroke-width':1},svg);
  const area=(a,b)=>'M'+B.map((r,i)=>x(i)+','+y(r[a])).join('L')+'L'+B.map((r,i)=>[i,r]).reverse().map(([i,r])=>x(i)+','+y(r[b])).join('L')+'Z';
  el('path',{d:area(0,4),fill:css('--band-out')},svg);
  el('path',{d:area(1,3),fill:css('--band-in')},svg);
  el('path',{d:'M'+B.map((r,i)=>x(i)+','+y(r[2])).join('L'),fill:'none',stroke:css('--median'),'stroke-width':2,'stroke-linejoin':'round'},svg);
  // livelli: target, ingresso, stop
  [[P.target,'Target',css('--good'),''],[P.entry,'Ingresso',css('--muted'),'4 4'],[P.stop,'Stop',css('--critical'),'']].forEach(([v,lab,c,dash])=>{
    el('line',{x1:m.l,x2:W-m.r,y1:y(v),y2:y(v),stroke:c,'stroke-width':2,'stroke-dasharray':dash},svg);
    const below=lab==='Stop';
    const t=el('text',{x:W-m.r,y:below?y(v)+15:y(v)-6,'text-anchor':'end','font-size':12,'font-weight':600,fill:css('--ink'),
      stroke:css('--surface'),'stroke-width':4,'paint-order':'stroke','stroke-linejoin':'round'},svg); t.textContent=lab+' '+fmt(v);
  });
  // hover
  const cross=el('line',{y1:m.t,y2:H-m.b,stroke:css('--axis'),'stroke-width':1,visibility:'hidden'},svg);
  const dot=el('circle',{r:4.5,fill:css('--median'),stroke:css('--surface'),'stroke-width':2,visibility:'hidden'},svg);
  const hit=el('rect',{x:m.l,y:m.t,width:W-m.l-m.r,height:H-m.t-m.b,fill:'transparent'},svg);
  hit.addEventListener('pointermove',ev=>{
    const r=svg.getBoundingClientRect(), px=(ev.clientX-r.left)*W/r.width;
    const i=Math.max(0,Math.min(n-1,Math.round((px-m.l)/(W-m.l-m.r)*(n-1)))), b=B[i];
    cross.setAttribute('x1',x(i));cross.setAttribute('x2',x(i));cross.setAttribute('visibility','visible');
    dot.setAttribute('cx',x(i));dot.setAttribute('cy',y(b[2]));dot.setAttribute('visibility','visible');
    tip(box,`<div class="t">${D.times[i]} (New York)</div>`+
      [['95° percentile',b[4]],['75°',b[3]],['Mediana',b[2]],['25°',b[1]],['5°',b[0]]].map(([k,v])=>`<div class="r"><span>${k}</span><span>${fmt(v)}</span></div>`).join(''),
      x(i)*r.width/W, y(b[2])*r.height/H);
  });
  hit.addEventListener('pointerleave',()=>{cross.setAttribute('visibility','hidden');dot.setAttribute('visibility','hidden');untip(box);});
}
function niceStep(raw){const p=Math.pow(10,Math.floor(Math.log10(raw)));for(const k of [1,2,2.5,5,10]) if(k*p>=raw) return k*p;return 10*p;}

function outcomes(){
  const box=document.getElementById('out'); if(!box) return;
  box.querySelector('svg')?.remove();
  const W=box.clientWidth, H=34, M=D.mc;
  const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,height:H,role:'img','aria-label':'Esiti delle simulazioni'}); box.prepend(svg);
  const parts=[['Target prima',M.p_target,css('--good')],['Né l’uno né l’altro entro la chiusura',M.p_neither,css('--neutral')],['Stop prima',M.p_stop,css('--critical')]];
  let x0=0; const gap=2, usable=W-gap*(parts.length-1);
  parts.forEach(([lab,p,c],k)=>{const w=usable*p;
    const r=el('rect',{x:x0,y:4,width:Math.max(0,w),height:26,rx:4,fill:c},svg);
    r.addEventListener('pointermove',ev=>{const b=box.getBoundingClientRect();tip(box,`<div class="t">${lab}</div><div class="r"><span>Quota</span><span>${fmt(p*100,1)} %</span></div>`,ev.clientX-b.left,ev.clientY-b.top);});
    r.addEventListener('pointerleave',()=>untip(box));
    x0+=w+gap;});
}

function history(){
  const box=document.getElementById('hist'); if(!box||!D.trades||!D.trades.length) return;
  box.querySelector('svg')?.remove();
  const T=D.trades, W=box.clientWidth, H=200, m={l:44,r:8,t:10,b:24};
  const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,height:H,role:'img','aria-label':'R di ogni caso storico'}); box.prepend(svg);
  const mx=Math.max(1,...T.map(t=>Math.abs(t.R)));
  const y=v=>m.t+(H-m.t-m.b)*(mx-v)/(2*mx);
  [-1,0,1].forEach(v=>{ if(Math.abs(v)<=mx){
    el('line',{x1:m.l,x2:W-m.r,y1:y(v),y2:y(v),stroke:v===0?css('--axis'):css('--grid'),'stroke-width':1},svg);
    const t=el('text',{x:m.l-8,y:y(v)+4,'text-anchor':'end','font-size':11,fill:css('--muted')},svg); t.textContent=(v>0?'+':'')+v+'R';}});
  const slot=(W-m.l-m.r)/T.length, bw=Math.max(2,Math.min(18,slot-2));
  T.forEach((t,i)=>{
    const cx=m.l+slot*i+slot/2, top=y(Math.max(0,t.R)), bot=y(Math.min(0,t.R)), h=Math.max(1,bot-top);
    const r=el('rect',{x:cx-bw/2,y:top,width:bw,height:h,rx:Math.min(4,bw/2),fill:t.R>=0?css('--pos'):css('--neg')},svg);
    const hb=el('rect',{x:m.l+slot*i,y:m.t,width:slot,height:H-m.t-m.b,fill:'transparent'},svg);
    const esito={target:'target',stop:'stop',close:'chiusa alle 16:00'}[t.outcome]||t.outcome;
    hb.addEventListener('pointermove',ev=>{const b=box.getBoundingClientRect();
      r.setAttribute('opacity','0.75');
      tip(box,`<div class="t">${t.date} · ${t.time}</div><div class="r"><span>Esito</span><span>${esito}</span></div><div class="r"><span>R</span><span>${(t.R>0?'+':'')+fmt(t.R)}</span></div><div class="r"><span>Ingresso</span><span>${fmt(t.entry)}</span></div>`,ev.clientX-b.left,ev.clientY-b.top);});
    hb.addEventListener('pointerleave',()=>{r.removeAttribute('opacity');untip(box);});
  });
  const f=el('text',{x:m.l,y:H-6,'font-size':11,fill:css('--muted')},svg); f.textContent=T[0].date;
  const l=el('text',{x:W-m.r,y:H-6,'text-anchor':'end','font-size':11,fill:css('--muted')},svg); l.textContent=T[T.length-1].date;
}
function draw(){fan();outcomes();history();}
draw();
let rt; window.addEventListener('resize',()=>{clearTimeout(rt);rt=setTimeout(draw,120);});
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change',draw);
"""


def _e(x):
    return html.escape(str(x))


def _num(x, d=2):
    s = "{:,.{d}f}".format(x, d=d)
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(p):
    return _num(p * 100, 1) + " %"


def _r(x):
    return ("+" if x > 0 else "") + _num(x, 3)


def write(path, tm, plan, orders, risk, opt_rows, min_edge, edge_ok, min_history, noise=None):
    mc, hist, p = tm["mc"], tm.get("history") or {}, tm["plan"]
    sym = p["symbol"]

    # verdetto
    if not edge_ok:
        cls, ic, title = "warn", "!", "Fermo: nessun vantaggio"
        body = ("La Macchina del Tempo dà un R medio simulato di %s, sotto il minimo di %s. "
                "Nessun ordine proposto." % (_r(mc["avg_R"]), _r(min_edge)))
        vc = "var(--warning)"
    elif risk and risk.get("block", 1) == 0:
        cls, ic, title, vc = "", "✓", "PASS: l'ordine rispetta i tuoi limiti", "var(--good)"
        body = "Ordine proposto in trader/orders.json. Per inviarlo usa /trader-broker: chiederà il tuo sì esplicito."
    else:
        cls, ic, title, vc = "", "✕", "BLOCK: trader-risk ha fermato l'ordine", "var(--critical)"
        body = "Leggi i motivi più sotto."

    tiles = [
        ("Target prima", _pct(mc["p_target"]), "a %s" % _num(p["target"])),
        ("Stop prima", _pct(mc["p_stop"]), "a %s" % _num(p["stop"])),
        ("Aperto alle 16:00", _pct(mc["p_neither"]), "né target né stop"),
        ("R medio simulato", _r(mc["avg_R"]), "%s replay" % _num(mc["replays"], 0)),
    ]
    if hist.get("avg_R") is not None:
        tiles.append(("R medio storico", _r(hist["avg_R"]),
                      "%d casi: %d target, %d stop" % (hist["triggered"], hist["target"], hist["stop"])))
    tiles_html = "".join('<div class="tile"><div class="k">%s</div><div class="v">%s</div><div class="d">%s</div></div>'
                         % (_e(k), _e(v), _e(d)) for k, v, d in tiles)

    opt_html = ""
    if opt_rows:
        rows = []
        for i, r in enumerate(opt_rows):
            if "skip" in r:
                rows.append("<tr><td>%s</td><td>%s</td><td colspan=7 style='text-align:left;color:var(--muted)'>saltata: %s</td></tr>"
                            % (_e(r["stop_rule"]), _e(r["target_rule"]), _e(r["skip"][:90])))
                continue
            hr = _r(r["hist_R"]) if r["hist_R"] is not None else "n/d"
            rows.append("<tr%s><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
                        "<td class='%s'>%s</td><td>%s <span style='color:var(--muted)'>(%d)</span></td><td class='%s'>%s</td></tr>" % (
                            " class='chosen'" if i == 0 else "", _e(r["stop_rule"]), _e(r["target_rule"]),
                            _num(r["stop"]), _num(r["target"]), _pct(r["p_target"]), _pct(r["p_stop"]),
                            "pos" if r["sim_R"] >= 0 else "neg", _r(r["sim_R"]), hr, r["hist_n"],
                            "pos" if r["score"] >= 0 else "neg", _r(r["score"])))
        opt_html = """<section class="card"><h2>Ottimizzatore</h2>
<p class="sub">Ogni combinazione di stop e target passata nella Macchina del Tempo (2.000 replay, stesso seme). Evidenziata la scelta.</p>
<div class="scroll"><table><thead><tr><th>Stop</th><th>Target</th><th>Prezzo stop</th><th>Prezzo target</th><th>Target prima</th><th>Stop prima</th><th>R sim.</th><th>R storico (casi)</th><th>Punti</th></tr></thead>
<tbody>%s</tbody></table></div>
%s<p class="note">Punti = R medio simulato, mediato con quello storico quando ci sono almeno %d casi. Scegliere il migliore su 60 giorni rischia di adattarsi al passato: trattalo come un indizio, non come una regola.</p></section>""" % (
            "".join(rows), ("<p class='note' style='color:var(--ink2)'><b>%s</b></p>" % _e(noise)) if noise else "", min_history)

    order_html = ""
    if orders and orders.get("orders"):
        o = orders["orders"][0]
        op = o.get("plan", {})
        res = (risk or {}).get("results") or [{}]
        reasons = res[0].get("reasons", []) + res[0].get("warnings", [])
        order_html = """<section class="card"><h2>Ordine proposto (non inviato)</h2>
<p class="sub">%s</p>
<div class="ticket"><div><div class="k">Azioni</div><div class="v">%s %s</div></div>
<div><div class="k">Ingresso</div><div class="v">%s</div></div>
<div><div class="k">Stop-loss</div><div class="v">%s</div></div>
<div><div class="k">Take-profit</div><div class="v">%s</div></div>
<div><div class="k">Perdita massima allo stop</div><div class="v">$%s</div></div>
<div><div class="k">Chiudere entro</div><div class="v">%s</div></div></div>%s</section>""" % (
            _e(o.get("why", "")), _e(o.get("qty")), _e(o.get("symbol")), _num(op.get("entry", 0)),
            _e(o.get("stop_loss_stop_price")), _e(o.get("take_profit_limit_price")), _num(op.get("max_loss", 0)),
            _e(op.get("flat_by", "")),
            ("<ul class='reasons'>%s</ul>" % "".join("<li>%s</li>" % _e(x) for x in reasons)) if reasons else "")

    hist_html = ""
    trades = hist.get("trades") or []
    if trades:
        rows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td class='%s'>%s</td></tr>" % (
            _e(t["date"]), _e(t["time"]), _num(t["entry"]), _e(t["outcome"]),
            "pos" if t["R"] >= 0 else "neg", _r(t["R"])) for t in trades)
        hist_html = """<section class="card"><h2>Lo storico: ogni volta che la regola è scattata</h2>
<p class="sub">La stessa regola sulle ultime %d sessioni reali: scattata %d volte, %d target, %d stop, %d chiuse alle 16:00. Una barra per caso, in R.</p>
<div class="chart" id="hist"><div class="tip"></div></div>
<div class="legend"><span><i style="background:var(--pos)"></i>Guadagno (R ≥ 0)</span><span><i style="background:var(--neg)"></i>Perdita (R &lt; 0)</span></div>
<details><summary>Tabella dei casi</summary><div class="scroll"><table><thead><tr><th>Data</th><th>Ora</th><th>Ingresso</th><th>Esito</th><th>R</th></tr></thead><tbody>%s</tbody></table></div></details></section>""" % (
            hist.get("sessions", 0), hist.get("triggered", 0), hist.get("target", 0), hist.get("stop", 0),
            hist.get("close", 0), rows)

    band_rows = "".join("<tr><td>%s</td><td></td>%s</tr>" % (_e(t), "".join("<td>%s</td>" % _num(v) for v in b))
                        for t, b in zip(mc["band_times"], mc["bands"]))

    data = {"bands": mc["bands"], "times": mc["band_times"], "mc": mc_slim(mc),
            "plan": {"entry": p["entry"], "stop": p["stop"], "target": p["target"]}, "trades": trades}
    data_json = json.dumps(data).replace("</", "<\\/")

    doc = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Macchina del Tempo %(sym)s</title><style>%(style)s</style></head><body><main>
<h1>%(sym)s · Macchina del Tempo</h1>
<p class="sub">%(date)s · ingresso %(entry)s alle %(etime)s · stop %(stop)s · target %(target)s (%(tr)sR) · rischio %(risk)s per azione</p>
<div class="verdict %(cls)s" style="--vc:%(vc)s"><div class="ic">%(ic)s</div><div><b>%(title)s</b><div class="sub">%(body)s</div></div></div>
<div class="tiles">%(tiles)s</div>
<section class="card"><h2>Il resto della giornata, %(replays)s volte</h2>
<p class="sub">Dove potrebbe trovarsi il prezzo, candela per candela, ricostruito dalle candele di %(sym)s alla stessa ora nelle ultime %(pool)d sessioni.</p>
<div class="chart" id="fan"><div class="tip"></div></div>
<div class="legend"><span><i class="line" style="background:var(--median)"></i>Mediana</span><span><i style="background:var(--band-in)"></i>50 %% centrale (25°–75°)</span><span><i style="background:var(--band-out)"></i>90 %% centrale (5°–95°)</span></div>
<details><summary>Tabella dei percentili</summary><div class="scroll"><table><thead><tr><th>Ora</th><th></th><th>5°</th><th>25°</th><th>Mediana</th><th>75°</th><th>95°</th></tr></thead><tbody>%(band_rows)s</tbody></table></div></details>
<h2 style="margin-top:22px">Come finiscono le simulazioni</h2>
<div class="chart" id="out"><div class="tip"></div></div>
<div class="legend"><span><i style="background:var(--good)"></i>Target prima %(pt)s</span><span><i style="background:var(--neutral)"></i>Aperto alle 16:00 %(pn)s</span><span><i style="background:var(--critical)"></i>Stop prima %(ps)s</span></div>
<p class="note">%(verdict)s Prezzo alle 16:00: mediana %(med)s, 90 %% delle simulazioni tra %(p5)s e %(p95)s. Seme %(seed)s.</p>
</section>
%(opt)s%(order)s%(hist)s
<footer>Una simulazione costruita dalle ultime sessioni di %(sym)s, non una previsione: utili, notizie e sospensioni possono fare cose che quelle sessioni non hanno mai fatto. Uno stop è un ordine, non una garanzia. Non è consulenza finanziaria. Generato da finanza.py con le skill trader-* (MIT).</footer>
</main><script type="application/json" id="data">%(data)s</script><script>%(script)s</script></body></html>
""" % {
        "sym": _e(sym), "style": STYLE, "date": _e(p["date"]), "entry": _num(p["entry"]), "etime": _e(p["entry_time"]),
        "stop": _num(p["stop"]), "target": _num(p["target"]), "tr": _num(p.get("target_r") or 0, 1).rstrip("0").rstrip(","),
        "risk": _num(p["risk_per_share"]), "cls": cls, "vc": vc, "ic": ic, "title": _e(title), "body": _e(body),
        "tiles": tiles_html, "replays": _num(mc["replays"], 0), "pool": mc.get("pool_sessions", 0),
        "band_rows": band_rows, "pt": _pct(mc["p_target"]), "pn": _pct(mc["p_neither"]), "ps": _pct(mc["p_stop"]),
        "verdict": _e(tm.get("verdict", "")), "med": _num(mc["median_close"]), "p5": _num(mc["p5_close"]),
        "p95": _num(mc["p95_close"]), "seed": _e(mc.get("seed")), "opt": opt_html, "order": order_html,
        "hist": hist_html, "data": data_json, "script": SCRIPT,
    }
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)


def mc_slim(mc):
    return {k: mc[k] for k in ("p_target", "p_stop", "p_neither", "avg_R")}
