"""Report HTML di settimana.py: i 5 titoli, le probabilità e la verifica sul passato.

Un file unico in trader/settimana.html, senza dipendenze esterne, tema chiaro e scuro.
"""

import html
import json

from finanza_report import STYLE as BASE_STYLE

STYLE = BASE_STYLE + r"""
:root{--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--meter:#e9e8e3}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--s1:#3987e5;--s2:#d95926;--s3:#199e70;--meter:#2c2c2a}}
:root[data-theme="dark"]{--s1:#3987e5;--s2:#d95926;--s3:#199e70;--meter:#2c2c2a}
.picks{display:grid;gap:14px;margin-top:16px}
.pick{min-width:0;background:var(--surface);border:1px solid var(--grid);border-radius:12px;padding:16px 20px}
.pick .top{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 14px}
.pick .rk{color:var(--muted);font-weight:600}
.pick .sym{font-size:22px;font-weight:700;letter-spacing:-.01em}
.pick .nm{color:var(--ink2)}
.pick .px{margin-left:auto;font-size:18px;font-weight:600}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 4px}
.chip{border:1px solid var(--grid);border-radius:999px;padding:2px 10px;font-size:12.5px;color:var(--ink2)}
.chip b{color:var(--ink);font-weight:600}
.meter{display:inline-block;width:70px;height:8px;border-radius:4px;background:var(--meter);vertical-align:middle;margin-right:8px;overflow:hidden}
.meter i{display:block;height:100%;background:var(--s1);border-radius:4px}
.aff{font-size:12px;border-radius:999px;padding:1px 8px;border:1px solid var(--grid)}
.aff.alta{color:var(--good-ink)}.aff.bassa{color:var(--crit-ink)}
h2.sec{margin:30px 0 0;font-size:20px}
"""

SCRIPT = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmt = (x, d=0) => Number(x).toLocaleString('it-IT', {minimumFractionDigits:d, maximumFractionDigits:d});
const pc = (x, d=1) => (x>0?'+':'') + fmt(x*100, d) + ' %';
const NS = 'http://www.w3.org/2000/svg';
function el(t,a,p){const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);if(p)p.appendChild(e);return e;}
function tip(box,h,x,y){const t=box.querySelector('.tip');t.innerHTML=h;t.style.display='block';const w=t.offsetWidth,W=box.clientWidth;
  t.style.left=Math.max(0,Math.min(W-w,x+14))+'px';t.style.top=Math.max(0,y-10)+'px';}
function untip(box){box.querySelector('.tip').style.display='none';}
const SER=[['strategia','5 titoli','--s1'],['paniere','Paniere','--s2'],['spy','SPY','--s3']];

function equity(){
  const box=document.getElementById('eq'); if(!box) return; box.querySelector('svg')?.remove();
  const W=box.clientWidth, narrow=W<520, H=Math.max(260,Math.min(380,W*0.45)), m={l:52,r:narrow?10:86,t:12,b:28};
  const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,height:H,role:'img','aria-label':'Crescita di 1 euro investito'}); box.prepend(svg);
  const C=D.curves, dates=D.dates, n=dates.length;
  const all=SER.flatMap(([k])=>C[k]); let lo=Math.min(...all), hi=Math.max(...all);
  const L=v=>Math.log(v), x=i=>m.l+(W-m.l-m.r)*i/(n-1), y=v=>m.t+(H-m.t-m.b)*(L(hi)-L(v))/(L(hi)-L(lo));
  for(const v of [0.75,1,1.5,2,3,4,5,6,8,10]){ if(v<lo*0.98||v>hi*1.02) continue;
    el('line',{x1:m.l,x2:W-m.r,y1:y(v),y2:y(v),stroke:v===1?css('--axis'):css('--grid'),'stroke-width':1},svg);
    const t=el('text',{x:m.l-8,y:y(v)+4,'text-anchor':'end','font-size':11,fill:css('--muted')},svg); t.textContent='×'+fmt(v,v%1?2:0);}
  let lastX=-1e9;
  dates.forEach((d,i)=>{ if(i>0 && d.slice(0,4)!==dates[i-1].slice(0,4) && x(i)-lastX>(narrow?56:40)){
    const t=el('text',{x:x(i),y:H-8,'text-anchor':'middle','font-size':11,fill:css('--muted')},svg); t.textContent=d.slice(0,4); lastX=x(i);}});
  el('line',{x1:m.l,x2:W-m.r,y1:H-m.b,y2:H-m.b,stroke:css('--axis')},svg);
  SER.slice().reverse().forEach(([k,lab,c])=>{
    el('path',{d:'M'+C[k].map((v,i)=>x(i).toFixed(1)+','+y(v).toFixed(1)).join('L'),fill:'none',stroke:css(c),'stroke-width':2,'stroke-linejoin':'round'},svg);});
  if(!narrow){ // etichette dirette, distanziate se si sovrappongono
    const ends=SER.map(([k,lab,c])=>({lab,c,v:C[k][n-1],yy:y(C[k][n-1])})).sort((a,b)=>a.yy-b.yy);
    for(let i=1;i<ends.length;i++) if(ends[i].yy-ends[i-1].yy<15) ends[i].yy=ends[i-1].yy+15;
    ends.forEach(e=>{const t=el('text',{x:W-m.r+8,y:e.yy+4,'font-size':12,fill:css('--ink')},svg);t.textContent=e.lab+' ×'+fmt(e.v,1);});
  }
  const cross=el('line',{y1:m.t,y2:H-m.b,stroke:css('--axis'),visibility:'hidden'},svg);
  const dots=SER.map(([k,,c])=>el('circle',{r:4,fill:css(c),stroke:css('--surface'),'stroke-width':2,visibility:'hidden'},svg));
  const hit=el('rect',{x:m.l,y:m.t,width:W-m.l-m.r,height:H-m.t-m.b,fill:'transparent'},svg);
  hit.addEventListener('pointermove',ev=>{const r=svg.getBoundingClientRect(),px=(ev.clientX-r.left)*W/r.width;
    const i=Math.max(0,Math.min(n-1,Math.round((px-m.l)/(W-m.l-m.r)*(n-1))));
    cross.setAttribute('x1',x(i));cross.setAttribute('x2',x(i));cross.setAttribute('visibility','visible');
    SER.forEach(([k],j)=>{dots[j].setAttribute('cx',x(i));dots[j].setAttribute('cy',y(C[k][i]));dots[j].setAttribute('visibility','visible');});
    tip(box,`<div class="t">${dates[i]}</div>`+SER.map(([k,lab,c])=>`<div class="r"><span><i style="display:inline-block;width:9px;height:9px;border-radius:2px;background:var(${c});margin-right:6px"></i>${lab}</span><span>×${fmt(C[k][i],2)}</span></div>`).join(''),x(i)*r.width/W,ev.clientY-r.top);});
  hit.addEventListener('pointerleave',()=>{cross.setAttribute('visibility','hidden');dots.forEach(d=>d.setAttribute('visibility','hidden'));untip(box);});
}

function years(){
  const box=document.getElementById('yr'); if(!box) return; box.querySelector('svg')?.remove();
  const Y=D.years, W=box.clientWidth, H=230, m={l:46,r:8,t:12,b:26};
  const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,height:H,role:'img','aria-label':'Rendimento per anno'}); box.prepend(svg);
  const vals=Y.flatMap(a=>[a.strategia,a.paniere]); const hi=Math.max(0.05,...vals), lo=Math.min(-0.05,...vals);
  const y=v=>m.t+(H-m.t-m.b)*(hi-v)/(hi-lo);
  const step=(hi-lo)>1?0.25:0.1;
  for(let v=Math.ceil(lo/step)*step; v<=hi+1e-9; v+=step){
    el('line',{x1:m.l,x2:W-m.r,y1:y(v),y2:y(v),stroke:Math.abs(v)<1e-9?css('--axis'):css('--grid')},svg);
    const t=el('text',{x:m.l-8,y:y(v)+4,'text-anchor':'end','font-size':11,fill:css('--muted')},svg); t.textContent=fmt(v*100)+'%';}
  const slot=(W-m.l-m.r)/Y.length, bw=Math.max(3,Math.min(22,(slot-8)/2));
  Y.forEach((a,i)=>{const cx=m.l+slot*i+slot/2;
    [['strategia','--s1',-1],['paniere','--s2',1]].forEach(([k,c,s])=>{const v=a[k],top=y(Math.max(0,v)),bot=y(Math.min(0,v));
      el('rect',{x:cx+(s<0?-bw-1:1),y:top,width:bw,height:Math.max(1,bot-top),rx:Math.min(4,bw/2),fill:css(c)},svg);});
    const t=el('text',{x:cx,y:H-8,'text-anchor':'middle','font-size':11,fill:css('--muted')},svg); t.textContent=(W<520?"'"+a.anno.slice(2):a.anno)+(a.settimane<40?'*':'');
    const hb=el('rect',{x:m.l+slot*i,y:m.t,width:slot,height:H-m.t-m.b,fill:'transparent'},svg);
    hb.addEventListener('pointermove',ev=>{const b=box.getBoundingClientRect();tip(box,`<div class="t">${a.anno}${a.settimane<40?' (parziale)':''}</div><div class="r"><span>5 titoli</span><span>${pc(a.strategia,0)}</span></div><div class="r"><span>Paniere</span><span>${pc(a.paniere,0)}</span></div>`,ev.clientX-b.left,ev.clientY-b.top);});
    hb.addEventListener('pointerleave',()=>untip(box));});
}
function draw(){equity();years();}
draw(); let rt; window.addEventListener('resize',()=>{clearTimeout(rt);rt=setTimeout(draw,120);});
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change',draw);
"""


def _e(x):
    return html.escape(str(x))


def _p(x, d=1, sign=True):
    if x is None:
        return "n/d"
    s = ("{:+.%df}" if sign else "{:.%df}") % d
    return s.format(x * 100).replace(".", ",") + " %"


def _num(x, d=2):
    return "{:,.{d}f}".format(x, d=d).replace(",", "X").replace(".", ",").replace("X", ".")


def write(path, r):
    m = r["backtest"]["metrics"]
    t = m.get("t_eccesso")
    sig = t is not None and t > 2

    banner = ("<b>Leggi prima.</b> Nessun algoritmo prevede la Borsa. Questo è trasparente e verificato sul passato: "
              "negli ultimi %d anni le sue scelte hanno fatto in media %s l'anno rispetto al paniere, ma con t = %s "
              "questo vantaggio %s. Le probabilità sono frequenze del passato, non promesse." % (
                  round(m["settimane"] / 52), _p(m.get("eccesso_annuo")), _num(t) if t is not None else "n/d",
                  "è statisticamente significativo" if sig else "<b>non è distinguibile dal caso</b>"))

    regime = ""
    if r.get("regime"):
        g = r["regime"]
        regime = " · mercato (SPY) %s la media a 200 giorni (%s)" % (
            "sopra" if g["spy_sopra_media200"] else "<b>sotto</b>", _p(g["spy_vs_media200"]))

    cards = []
    for n, p in enumerate(r["picks"], 1):
        s = p["signal"]
        rows = []
        for label, h in p["horizons"].items():
            st = h["simili"]
            if not st.get("n"):
                rows.append("<tr><td>%s</td><td colspan=5 style='text-align:left'>n/d</td></tr>" % _e(label))
                continue
            rows.append(
                "<tr><td>%s</td><td><span class='meter'><i style='width:%.0f%%'></i></span>%s</td>"
                "<td class='%s'>%s</td><td>%s / %s</td><td>%d <span style='color:var(--muted)'>(%d)</span></td>"
                "<td><span class='aff %s'>%s</span></td></tr>" % (
                    _e(label), st["p_gain"] * 100, _p(st["p_gain"], 0, False),
                    "pos" if st["median"] >= 0 else "neg", _p(st["median"]), _p(st["p10"]), _p(st["p90"]),
                    st["n"], h["indipendenti"], h["affidabilita"], h["affidabilita"]))
        cards.append("""<article class="pick"><div class="top"><span class="rk">%d</span><span class="sym">%s</span>
<span class="nm">%s</span><span class="px">%s</span></div>
<div class="chips"><span class="chip">momentum 12-1 <b>%s</b></span><span class="chip">volatilità <b>%s</b></span>
<span class="chip">sopra la media 200 <b>%s</b></span><span class="chip">punteggio <b>%s</b></span></div>
<div class="scroll"><table><thead><tr><th>Orizzonte</th><th>Prob. di guadagno</th><th>Tipico (mediana)</th><th>Range 10–90 %%</th><th>Casi (indip.)</th><th>Affidabilità</th></tr></thead>
<tbody>%s</tbody></table></div></article>""" % (
            n, _e(p["symbol"]), _e(p["name"]), _num(p["price"]), _p(s["mom"]), _p(s["vol"], sign=False),
            _p(s["vs_sma"]), _num(s["score"]), "".join(rows)))

    rec_rows = "".join(
        "<tr><td>%s</td><td>%s</td><td class='%s'>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%d</td></tr>" % (
            _e(k), _p(v["algoritmo"].get("p_gain"), 0, False),
            "pos" if (v["algoritmo"].get("median") or 0) >= 0 else "neg", _p(v["algoritmo"].get("median")),
            _p(v["paniere"].get("p_gain"), 0, False), _p(v["paniere"].get("median")),
            _p(v["batte_paniere"], 0, False), v["indipendenti"]) for k, v in r["record"].items())

    met_rows = "".join("<tr><td>%s</td><td></td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        lab, _p(m[k]["cagr"]), _p(m[k]["max_drawdown"]), _p(m[k]["totale"], 0))
        for k, lab in (("strategia", "5 titoli, ogni settimana"), ("paniere", "Paniere: tutti, stesso peso"),
                       ("spy", "SPY (S&P 500)")))

    rank_rows = "".join("<tr><td>%d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        i + 1, _e(x["symbol"]), _num(x["score"]), _p(x["mom"]), _p(x["vol"], sign=False),
        "sì" if x["above"] else "<span class='neg'>no</span>") for i, x in enumerate(r["classifica"]))

    data = {"dates": r["backtest"]["dates"], "curves": r["backtest"]["curves"], "years": m["anni"]}
    me = r.get("metodo", {})

    doc = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Titoli della settimana</title>
<style>%(style)s</style></head><body><main>
<h1>I 5 titoli della settimana</h1>
<p class="sub">Dati fino al %(asof)s · universo %(univ)d grandi titoli USA (S&amp;P 100)%(regime)s</p>
<div class="verdict warn" style="--vc:var(--warning)"><div class="ic">!</div><div class="sub">%(banner)s</div></div>
<div class="picks">%(cards)s</div>
<p class="note"><b>Prob. di guadagno</b>: quante volte, quando questo titolo si trovava in condizioni simili (tra il 20 %% migliore del punteggio e sopra la media a 200 giorni), era in guadagno dopo quel periodo. <b>Tipico</b>: il risultato mediano. <b>Range</b>: 8 casi su 10 sono finiti in questo intervallo. <b>Casi</b>: finestre storiche; tra parentesi quelle che non si sovrappongono, cioè le osservazioni davvero indipendenti. A 1 anno sono pochissime: quel numero è il più fragile.</p>

<h2 class="sec">La verifica: come sarebbe andata</h2>
<p class="sub">Ogni settimana dal %(da)s al %(a)s: stessa regola, solo i dati disponibili in quel momento, %(costo)s di costo per ogni titolo cambiato.</p>
<section class="card"><h2>Crescita di 1 € investito</h2><p class="sub">Scala logaritmica: la stessa pendenza vuol dire lo stesso rendimento percentuale.</p>
<div class="chart" id="eq"><div class="tip"></div></div>
<div class="legend"><span><i class="line" style="background:var(--s1)"></i>5 titoli, ogni settimana</span><span><i class="line" style="background:var(--s2)"></i>Paniere (tutti i titoli, stesso peso)</span><span><i class="line" style="background:var(--s3)"></i>SPY (S&amp;P 500)</span></div>
<div class="scroll" style="margin-top:12px"><table><thead><tr><th>Portafoglio</th><th></th><th>Annuo</th><th>Calo massimo</th><th>Totale</th></tr></thead><tbody>%(met)s</tbody></table></div>
<p class="note">Settimane in guadagno %(wpos)s · settimane meglio del paniere %(wbeat)s · vantaggio medio sul paniere %(ex)s l'anno, t = %(t)s (%(tverd)s).</p></section>

<section class="card"><h2>Anno per anno</h2><p class="sub">Se funziona davvero, dovrebbe battere il paniere quasi ogni anno. * = anno parziale.</p>
<div class="chart" id="yr"><div class="tip"></div></div>
<div class="legend"><span><i style="background:var(--s1)"></i>5 titoli</span><span><i style="background:var(--s2)"></i>Paniere</span></div></section>

<section class="card"><h2>Tutte le scelte passate dell'algoritmo</h2><p class="sub">Ogni titolo scelto in ogni settimana della verifica, confrontato con tutti i titoli dell'universo nelle stesse date.</p>
<div class="scroll"><table><thead><tr><th>Orizzonte</th><th>Scelte: prob. +</th><th>Scelte: tipico</th><th>Paniere: prob. +</th><th>Paniere: tipico</th><th>Settimane sopra il paniere</th><th>Casi indip.</th></tr></thead><tbody>%(rec)s</tbody></table></div></section>

<section class="card"><h2>Classifica completa (prime 15)</h2>
<div class="scroll"><table><thead><tr><th>#</th><th>Titolo</th><th>Punteggio</th><th>Momentum 12-1</th><th>Volatilità</th><th>Sopra media 200</th></tr></thead><tbody>%(rank)s</tbody></table></div></section>

<section class="card"><h2>Il metodo</h2>
<p class="sub">Punteggio = rendimento da %(lb)d a %(sk)d giorni di borsa fa (momentum 12-1, Jegadeesh e Titman 1993), diviso per la volatilità annualizzata degli ultimi %(vw)d giorni. Si scelgono i %(top)d punteggi più alti tra i titoli sopra la loro media a %(sw)d giorni. I parametri sono quelli standard della letteratura, non sono stati ottimizzati su questi dati. Prezzi di chiusura corretti per dividendi e split (Yahoo Finance, non ufficiale).</p>
<p class="note"><b>Limiti.</b> L'universo è l'S&amp;P 100 di oggi: nel passato contiene solo aziende sopravvissute e cresciute, quindi sia la strategia sia il paniere sembrano migliori di quanto sarebbero stati davvero (bias di sopravvivenza); il confronto tra i due è più affidabile dei numeri assoluti. Si compra alla chiusura del giorno del segnale. Niente tasse. Il momentum può crollare bruscamente nei rimbalzi dopo un mercato ribassista.</p></section>
<footer>Frequenze del passato, non previsioni. Non è consulenza finanziaria. Generato da settimana.py.</footer>
</main><script type="application/json" id="data">%(data)s</script><script>%(script)s</script></body></html>
""" % {
        "style": STYLE, "asof": _e(r["asof"]), "univ": r["universo"], "regime": regime, "banner": banner,
        "cards": "".join(cards), "da": _e(r["backtest"]["da"]), "a": _e(r["backtest"]["a"]),
        "costo": _p(r["backtest"]["costo_andata_ritorno"], 2, False), "met": met_rows,
        "wpos": _p(m["settimane_positive"], 0, False), "wbeat": _p(m["settimane_sopra_paniere"], 0, False),
        "ex": _p(m.get("eccesso_annuo")), "t": _num(t) if t is not None else "n/d",
        "tverd": "significativo" if sig else "non distinguibile dal caso: servirebbe t > 2",
        "rec": rec_rows, "rank": rank_rows, "lb": me.get("lookback", 252), "sk": me.get("skip", 21),
        "vw": me.get("vol_win", 63), "sw": me.get("sma_win", 200), "top": me.get("top", 5),
        "data": json.dumps(data).replace("</", "<\\/"), "script": SCRIPT,
    }
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
