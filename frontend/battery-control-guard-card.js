// Battery Control Guard · Home Assistant card
// Derived from the existing charging-dashboard Guard sheet, without site-specific settings.
// No direct EVCC or KOSTAL control. Mode selection affects only what is displayed.
'use strict';
(function () {
  const STYLE = ":host{display:block;container-type:inline-size;color:#f3f6f5;font:14px/1.45 Arial,sans-serif;color-scheme:dark;box-sizing:border-box} *,*::before,*::after{box-sizing:border-box} [hidden]{display:none!important}/* Mokka Guard: Screenshot-derived clean, near-black independent sheet. */\n.guard-refined{display:block!important;max-height:none!important;overflow:visible!important;padding:0 0 24px!important;color:#f3f6f5}\n.guard-refined[hidden]{display:none!important}\n.guard-sheet{border:1px solid #2a3034;border-radius:18px;background:#090b0c;padding:24px 26px 22px;color:#f3f6f5;box-shadow:0 14px 45px #0002}\n.guard-sheet-top{display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:16px;font-weight:700;margin:0 0 26px}\n.guard-sheet-name{display:flex;align-items:center;gap:10px}\n.guard-shield{color:#23bd83;font-size:20px}\n.guard-statusbadge{background:#182220;border-radius:999px;color:#60dcb3;font-size:11px;font-weight:500;padding:5px 9px;white-space:nowrap}\n.guard-label{font-size:12px;color:#b1bac0;margin-bottom:8px}\n.guard-num{font-size:23px;font-weight:650;font-variant-numeric:tabular-nums;line-height:1.25}\n.guard-under{color:#94a3ad;font-size:11px;margin-top:7px}\n.guard-kpis{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:26px;padding:0 12px 25px}\n.guard-kpis.four{grid-template-columns:repeat(2,minmax(0,1fr));row-gap:28px}\n.guard-separator{height:1px;background:#282b2d;border:0;margin:12px 0 26px}\n.guard-section-title{font-size:15px;margin:0 0 17px;font-weight:500;color:#edf2f0}\n.guard-radio-stack{display:flex;flex-direction:column;gap:14px;margin-bottom:12px}\n.guard-radio-row{display:flex;align-items:center;gap:10px;font-size:14px;color:#e6eaeb;cursor:pointer}\n.guard-radio-row input{appearance:none;cursor:pointer;width:19px;height:19px;border:1px solid #686e74;border-radius:50%;display:inline-grid;place-items:center;margin:0;background:#0d1010;flex-shrink:0}\n.guard-radio-row input:checked{background:#f1f5f5;border-color:#f1f5f5}\n.guard-radio-row input:checked::after{content:\"\";background:#202528;width:6px;height:6px;border-radius:50%}\n.guard-radio-row input:focus-visible,.guard-refined button:focus-visible,.guard-reserve-slider:focus-visible{outline:3px solid #32bb8b;outline-offset:3px}\n.guard-mode-hint{margin:14px 0 0;color:#a2b2b6;font-size:12px;line-height:1.5}\n.guard-reserve-top{display:flex;justify-content:space-between;align-items:center;gap:15px;font-size:13px;margin:16px 0 14px}\n.guard-reserve-top output{font-size:14px;font-variant-numeric:tabular-nums}\n.guard-reserve-slider{width:100%;height:8px;accent-color:#e9f0f2;cursor:pointer}\n.guard-sim-note{font-size:12px;color:#9aadb5;margin:11px 0 2px;line-height:1.5}\n.guard-pane[hidden]{display:none!important}\n.guard-pane-heading{font-size:11px;letter-spacing:1px;text-transform:uppercase;color:#bac5ca;margin:2px 0 24px}\n.guard-forecast-list{display:flex;flex-direction:column;gap:19px;padding:0 6px 16px}\n.guard-forecast-row{display:flex;align-items:center;gap:14px}\n.guard-f-icon{display:grid;place-items:center;color:#abb9c4;font-size:21px;width:24px;flex-shrink:0}\n.guard-f-main{flex:1;min-width:0}\n.guard-f-name{font-size:14px;color:#ecf0f1}\n.guard-f-desc{font-size:11px;color:#a1afb8;margin-top:4px}\n.guard-f-tag{font-size:12px;color:#a8b2bc;text-align:right}\n.guard-history-heading{font-weight:600;font-size:15px;margin:18px 0 10px}\n.guard-chart-wrap{background:#0b1116;border:1px solid #28313a;border-radius:12px;padding:10px 8px 4px}\n.guard-chart-wrap ha-card{box-shadow:none}\n.guard-desc{color:#a4b3bf;font-size:12px;line-height:1.55}\n.guard-refined button.guard-primary-btn{background:#163c34;color:#dfffee;border:1px solid #2d9c75;border-radius:9px;padding:11px 14px;cursor:pointer;font-size:13px;font-weight:600}\n.guard-refined button.guard-primary-btn:hover{background:#205243}\n.guard-detail{border-top:1px solid #282b2d;margin-top:22px;padding-top:12px}\n.guard-detail>summary{cursor:pointer;color:#b5c5d0;font-size:13px;padding:8px 0}\n.guard-tech-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0}\n.guard-tech-grid>.box{min-width:0}\n.guard-refined .box{padding:7px}\n.guard-report{border:1px solid #2e3537;border-radius:10px;background:#10191b;color:#eef5f2;margin-top:15px;overflow:hidden}\n.guard-report>summary{font-size:13px;padding:13px;cursor:pointer}\n.guard-report iframe{display:block;width:100%;height:920px;border:0;background:#08101a}\n.guard-mode-info{color:#92b9ae}\n@container(max-width:899px){\n.guard-sheet{padding:17px 15px}\n.guard-kpis{gap:18px;padding:0 4px 20px}\n.guard-tech-grid{grid-template-columns:1fr}\n.guard-sheet-top{align-items:start}\n.guard-num{font-size:20px}\n.guard-report iframe{height:760px}\n}\n.bcg-diagnostics{white-space:pre-wrap;word-break:break-word;font-size:12px;color:#abbac2}.guard-sheet{max-width:100%;box-sizing:border-box}.guard-reserve-slider:disabled{opacity:.4;cursor:not-allowed}";
  const TEMPLATE = "<section class=\"guard-refined\">\n <div class=\"guard-sheet\">\n  <div class=\"guard-sheet-top\"><span class=\"guard-sheet-name\"><span class=\"guard-shield\">♢</span>KOSTAL Battery-Guard</span><span class=\"guard-statusbadge\" id=\"guard-shell-mode\">Klassisch · Ansicht</span></div>\n  <div class=\"guard-kpis\">\n   <div><div class=\"guard-label\">Speicher-SoC</div><div class=\"guard-num\" id=\"guard-kpi-soc\">—</div><div class=\"guard-under\">Hausakku · KOSTAL</div></div>\n   <div><div class=\"guard-label\">Entladefreigabe</div><div class=\"guard-num\" id=\"guard-kpi-limit\">—</div><div class=\"guard-under\" id=\"guard-kpi-limit-note\">Aktuelles KOSTAL-Register 1040</div></div>\n  </div>\n  <hr class=\"guard-separator\">\n  <h2 class=\"guard-section-title\">Betriebsmodus</h2>\n  <div class=\"guard-radio-stack\" role=\"radiogroup\" aria-label=\"Ansicht Battery-Guard\">\n   <label class=\"guard-radio-row\"><input type=\"radio\" name=\"bcg-card-view\" data-guard-ui-mode=\"klassisch\" checked>Klassische Leistungsbegrenzung</label>\n   <label class=\"guard-radio-row\"><input type=\"radio\" name=\"bcg-card-view\" data-guard-ui-mode=\"intelligent\">Intelligent – dynamische PV-Erholung <span id=\"guard-mode-version\" style=\"font-size:11px;color:#79bd9e\">(wird geladen)</span></label>\n  </div>\n  <div id=\"guard-mode-info\" class=\"guard-mode-hint\" role=\"status\">Die Ansichtswahl schaltet den Guard nicht um.</div>\n  <hr class=\"guard-separator\">\n  <h2 class=\"guard-section-title\">Einstellungen</h2>\n  <div class=\"guard-reserve-top\"><label for=\"guard-reserve-slider\">Gesamter Sicherheits-SoC (HA, intelligent)</label><output id=\"guard-reserve-value\" for=\"guard-reserve-slider\">15 %</output></div>\n  <input class=\"guard-reserve-slider\" id=\"guard-reserve-slider\" type=\"range\" min=\"8\" max=\"30\" step=\"1\" value=\"15\" aria-label=\"Gesamter Sicherheits-SoC für die intelligente Steuerung\">\n  <p id=\"bcg-save-feedback\" class=\"guard-desc\" role=\"status\">Einstellungen nur mit konfigurierter HA-Reserve-Entität möglich.</p><p class=\"guard-sim-note\">Nur bei konfigurierter Home-Assistant-Reserve-Entität wird dieser Wert geschrieben. Die Ansichtswahl ändert keine Steuerung.</p>\n  <div class=\"guard-v070-panel\" style=\"margin:16px 0 8px;padding:14px;border-radius:12px;border:1px solid #326172;background:#102a32\">\n   <h2 class=\"guard-section-title\" style=\"margin:0 0 10px\">Intelligente Freigabe · Live</h2>\n   <div class=\"guard-kpis four\">\n    <div><div class=\"guard-label\">Tatsächlich freigegeben</div><div class=\"guard-num\" id=\"guard-v070-active\" style=\"font-size:23px\">—</div><div class=\"guard-under\">Controllerberechtigung</div></div>\n    <div><div class=\"guard-label\">Würde bei geplantem Laden freigeben?</div><div class=\"guard-num\" id=\"guard-v070-would\" style=\"font-size:23px\">—</div><div class=\"guard-under\">Reine Modellvorschau</div></div>\n    <div><div class=\"guard-label\">Mögliches Zusatzbudget</div><div class=\"guard-num\" id=\"guard-v070-potential\">—</div><div class=\"guard-under\">Dynamisch nach Prognose und Sicherheitsreserve</div></div>\n    <div><div class=\"guard-label\">Bereits verbraucht / verbleibend</div><div class=\"guard-num\" id=\"guard-v070-ledger\" style=\"font-size:20px\">—</div><div class=\"guard-under\">Nur aktive Berechtigung</div></div>\n   </div>\n   <div class=\"guard-kpis\" style=\"padding-top:10px\">\n    <div><div class=\"guard-label\">Nächste prognostizierte PV-Erholung</div><div class=\"guard-num\" id=\"guard-v070-recovery\" style=\"font-size:19px\">—</div></div>\n    <div><div class=\"guard-label\">Wirksame Sicherheitsreserve</div><div class=\"guard-num\" id=\"guard-v070-reserve\" style=\"font-size:19px\">—</div></div>\n    <div><div class=\"guard-label\">Prognosealter</div><div class=\"guard-num\" id=\"guard-v070-age\" style=\"font-size:19px\">—</div></div>\n   </div>\n   <p class=\"guard-desc\" role=\"status\" id=\"guard-v070-reason\" style=\"margin:12px 0 4px\">Live-Entscheidung wird geladen …</p>\n   <p class=\"guard-under\" id=\"guard-v070-update\" style=\"margin:0\">Controllerstatus wird geladen · kein paralleler KOSTAL-Schreiber</p>\n  </div>\n  <div class=\"guard-pane\" data-guard-pane=\"klassisch\">\n   <hr class=\"guard-separator\">\n   <h2 class=\"guard-section-title\">Klassische Regelung</h2>\n   <p class=\"guard-desc\">Der Guard begrenzt bei geschützter Schnell- oder Planladung die Hausspeicherentladung. Aktivierungsstatus und tatsächliche Grenzwerte kommen aus Home Assistant.</p>\n   <div class=\"guard-kpis\" style=\"padding-top:12px\">\n     <div><div class=\"guard-label\">KOSTAL Mindest-SoC (real)</div><div class=\"guard-num\" id=\"guard-kpi-min-classic\">—</div></div>\n     <div><div class=\"guard-label\">Aktueller Status</div><div class=\"guard-num\" id=\"guard-operating\" style=\"font-size:16px\">—</div></div>\n   </div>\n  </div>\n  <div class=\"guard-pane\" data-guard-pane=\"intelligent\" hidden>\n   <hr class=\"guard-separator\">\n   <div class=\"guard-pane-heading\">Speicherübersicht</div>\n   <div class=\"guard-kpis four\">\n    <div><div class=\"guard-label\">Aktueller SoC</div><div class=\"guard-num\" id=\"guard-int-soc\">—</div></div>\n    <div><div class=\"guard-label\">Mindest-SoC (KOSTAL real)</div><div class=\"guard-num\" id=\"guard-int-min\">—</div></div>\n    <div><div class=\"guard-label\">Prognostizierter Mindest-SoC bis Folgetagesende</div><div class=\"guard-num\" id=\"guard-int-plan\">—</div><div class=\"guard-under\" id=\"guard-int-plan-note\">Neue Prognose wird geladen</div></div>\n    <div><div class=\"guard-label\">Entladefreigabe · real 1040</div><div class=\"guard-num\" id=\"guard-int-limit\">—</div></div>\n   <div style=\"grid-column:1/-1;padding:9px 0;border-top:1px solid #243333\">\n     <div class=\"guard-label\">Rechnerischer Zusatzspielraum · bei gewählter SoC-Reserve, ohne zusätzlichen kWh-Abschlag</div>\n     <div class=\"guard-num\" id=\"guard-int-budget\">—</div>\n     <div class=\"guard-under\">Rechnerischer Spielraum, keine automatische Freigabe. Tatsächliche Berechtigung siehe Live-Status.</div>\n   </div>\n   </div>\n   <hr class=\"guard-separator\">\n   <h2 class=\"guard-section-title\">Prognoseprüfung</h2>\n   <div class=\"guard-forecast-list\">\n     <div class=\"guard-forecast-row\"><span class=\"guard-f-icon\">☼</span><div class=\"guard-f-main\"><div class=\"guard-f-name\">EVCC-PV-Prognose</div><div class=\"guard-f-desc\">Erwarteter Ertrag und stündlicher Verlauf</div></div><span class=\"guard-f-tag\" id=\"guard-evcc-forecast\">Datenquelle</span></div>\n     <div class=\"guard-forecast-row\"><span class=\"guard-f-icon\">☁</span><div class=\"guard-f-main\"><div class=\"guard-f-name\">HA-Wetterprognose</div><div class=\"guard-f-desc\">Bewölkung und Niederschlag · noch kein Einfluss auf die Steuerung</div></div><span class=\"guard-f-tag\" id=\"guard-weather\">—</span></div>\n     <div class=\"guard-forecast-row\"><span class=\"guard-f-icon\">⌁</span><div class=\"guard-f-main\"><div class=\"guard-f-name\">PV-Ertragshistorie</div><div class=\"guard-f-desc\">Vergleich zwischen Prognose und Realität · abhängig von der lokalen Datengrundlage</div></div><span class=\"guard-f-tag\">Lernbasis</span></div>\n   </div>\n   <p class=\"guard-desc\">Eine Prognose ist keine Freigabe. Nur ein gültiger Live-Status kann eine tatsächliche Berechtigung bestätigen.</p>\n  </div>\n  <hr class=\"guard-separator\">\n  <h2 class=\"guard-history-heading\">Verlaufsdiagramm</h2>\n  <p class=\"guard-desc\">Hausakku-SoC und realer KOSTAL-Mindest-SoC aus den letzten 48 Stunden.</p>\n  <div class=\"guard-chart-wrap\" id=\"guardtrend\"></div>\n  <details class=\"guard-detail\"><summary>Technische Details und Datenqualität</summary><p class=\"guard-desc\">Die Anzeige ist rein informativ. Überwachung und Steuerung können bei veralteten Messwerten nicht zuverlässig beurteilt werden.</p><pre id=\"bcg-diagnostics\" class=\"bcg-diagnostics\">Daten werden geladen</pre></details>\n </div>\n </section>";
  const REASONS = {
    ACTUAL_PERMISSION_ACTIVE:'Zusatzfreigabe erteilt; KOSTAL-Begrenzung wird vom Guard geregelt.',
    FAST_MODE_NO_RELEASE:'Schnellladen: keine intelligente Zusatzfreigabe.',
    NO_ACTIVE_PLAN:'Kein aktiver Ladeplan; ein mögliches Budget ist nur eine Vorschau.',
    PLAN_SCHEDULED_WAITING:'Ladeplan erkannt; Freigabe erst bei tatsächlichem Ladebeginn.',
    FORECAST_OR_DATA_INVALID:'Prognose fehlt, ist veraltet oder unbrauchbar.',
    NO_SUSTAINABLE_PV_RECOVERY:'Keine nachhaltige PV-Erholung prognostiziert.',
    BUDGET_INSUFFICIENT:'Kein ausreichendes Zusatzbudget für die Batteriereserve.',
    MEASUREMENT_INVALID:'Messwerte inkonsistent: Zusatzfreigabe gesperrt.',
    EVCC_OPTIMIZER_CONFLICT:'Konkurrierende Batterieoptimierung erkannt.',
    HA_RESERVE_UNAVAILABLE:'Konfigurierte HA-Sicherheitsreserve nicht abrufbar.',
    ELIGIBLE_IF_GATES_PASS:'Voraussichtlich möglich, aber noch nicht tatsächlich freigegeben.',
    WAITING_FOR_EVCC_CHARGING:'Keine geeignete aktive EVCC-Ladung.',
    FORECAST_PAUSED:'Zusatzfreigabe mangels gültiger Prognose pausiert.',
    PRIORITY_PAUSED:'Zusatzfreigabe aufgrund anderer Ladepriorität pausiert.',
    SESSION_LOCKED:'Diese Sitzung wurde aus Sicherheitsgründen gesperrt.',
    BUDGET_EXHAUSTED:'Das Zusatzbudget ist erschöpft.',
    NO_CURRENT_EVCC_STATE:'EVCC-Messwerte nicht verfügbar.'
  };
  const DEFAULT_URLS = {
    status:'/local/guard/guard-v070-status.json',
    forecast:'/local/guard/guard-recovery-v072.json'
  };
  const KEYS = ['battery_soc','kostal_min_soc','discharge_limit','guard_status','guard_requested','reserve','forecast_ready','weather','history_soc','history_min_soc'];
  const format = (num,digits=1,suffix='') => {
    const n=Number(num);
    return num===null||num===undefined||num===''||!Number.isFinite(n)?'—':n.toLocaleString('de-DE',{maximumFractionDigits:digits})+suffix;
  };
  class BatteryControlGuardCard extends HTMLElement {
    constructor(){
      super();this.attachShadow({mode:'open'});this.view='klassisch';
      this.status=null;this.forecast=null;this.entities={};this.urls={...DEFAULT_URLS};
      this.lastStatus=0;this.lastForecast=0;this.working=false;this.timer=null;
      this.requestedReserve=null;this.reservePending=false;
    }
    setConfig(cfg){
      if(!cfg||typeof cfg!=='object')throw Error('Battery Control Guard: card config required');
      this.config=cfg;this.entities={};
      const supplied=cfg.entities||{};
      if(supplied&&typeof supplied!=='object')throw Error('entities must be a map');
      for(const key of KEYS){
        const entity=supplied[key];
        if(entity!==undefined&&entity!==null&&entity!==''){
          if(typeof entity!=='string'||!/^(sensor|binary_sensor|input_number|weather)\.[a-z0-9_]+$/.test(entity))
            throw Error('Invalid entity mapping: '+key);
          this.entities[key]=entity;
        }
      }
      this.urls={...DEFAULT_URLS,...(cfg.urls||{})};
      for(const key of ['status','forecast']){
        const path=this.urls[key];
        if(typeof path!=='string'||!/^\/local\/[a-zA-Z0-9_./-]+\.json$/.test(path)||path.includes('..'))
          throw Error('Unsafe or invalid same-origin JSON path: '+key);
      }
      this.build();
    }
    set hass(h){this._hass=h;if(this.historyCard)this.historyCard.hass=h;this.renderHass();}
    getCardSize(){return 9;}
    connectedCallback(){
      if(!this.shadowRoot.getElementById('guard-shell-mode'))this.build();
      if(!this.timer)this.timer=setInterval(()=>this.refresh(),15000);
      this.refresh(true);this.renderHass();
    }
    disconnectedCallback(){if(this.timer){clearInterval(this.timer);this.timer=null;}}
    setText(id,value){
      const e=this.shadowRoot.getElementById(id);
      if(e)e.textContent=value===undefined||value===null?'—':String(value);
    }
    build(){
      this.shadowRoot.innerHTML='<style>'+STYLE+'</style>'+TEMPLATE;
      this.shadowRoot.querySelectorAll('[data-guard-ui-mode]').forEach(input=>
        input.addEventListener('change',()=>{if(input.checked)this.setView(input.dataset.guardUiMode);}));
      const slider=this.shadowRoot.getElementById('guard-reserve-slider');
      slider.addEventListener('change',()=>this.sendReserve(Number(slider.value)));
      this.setView(this.view);this.renderHass();this.renderStatus();this.renderForecast();this.mountHistory();
    }
    setView(v){
      this.view=v==='intelligent'?'intelligent':'klassisch';
      for(const el of this.shadowRoot.querySelectorAll('[data-guard-ui-mode]'))el.checked=el.dataset.guardUiMode===this.view;
      for(const el of this.shadowRoot.querySelectorAll('[data-guard-pane]'))el.hidden=el.dataset.guardPane!==this.view;
      this.setText('guard-shell-mode',this.view==='klassisch'?'Klassisch · Ansicht':'Intelligent · Ansicht');
      this.setText('guard-mode-info','Ansichtswahl: '+(this.view==='klassisch'?'klassische Schutzansicht':'intelligente Prognoseansicht')+'. Keine Umschaltung der Steuerung.');
    }
    entityState(key){
      const id=this.entities[key];return id?this._hass?.states?.[id]||null:null;
    }
    value(key){
      const raw=this.entityState(key)?.state;
      if(raw===undefined||raw===null||['unknown','unavailable','none',''].includes(String(raw).toLowerCase()))return null;
      return raw;
    }
    renderHass(){
      if(!this.shadowRoot.getElementById('guard-kpi-soc'))return;
      const soc=this.value('battery_soc');
      const min=this.value('kostal_min_soc');
      const limit=this.value('discharge_limit');
      const backupSoc=validStatus(this.status)?this.status.batterySocPct:null;
      for(const id of ['guard-kpi-soc','guard-int-soc'])this.setText(id,format(soc??backupSoc,1,' %'));
      for(const id of ['guard-kpi-min-classic','guard-int-min'])this.setText(id,format(min,1,' %'));
      for(const id of ['guard-kpi-limit','guard-int-limit'])this.setText(id,format(limit,0,' W'));
      this.setText('guard-operating',this.value('guard_status')||'Nicht verfügbar');
      this.setText('guard-kpi-limit-note',this.value('guard_requested')==='on'
        ? 'Begrenzung laut HA angefordert · Register 1040' : '1040-Messwert, keine aktive Anforderung bestätigt');
      this.setText('guard-evcc-forecast',this.value('forecast_ready')==='on'?'Datenquelle verfügbar':'Nicht bestätigt');
      const weather=this.value('weather');
      this.setText('guard-weather',weather?'Verfügbar · '+weather:'Nicht konfiguriert');
      const reserve=this.value('reserve');
      const reserveInput=this.shadowRoot.getElementById('guard-reserve-slider');
      const validReserve=this.entities.reserve?.startsWith('input_number.')&&reserve!==null&&
        Number.isFinite(Number(reserve))&&Number(reserve)>=8&&Number(reserve)<=30;
      reserveInput.disabled=!validReserve||this.reservePending;
      if(validReserve&&!this.reservePending){
        reserveInput.value=String(Math.round(Number(reserve)));
        this.requestedReserve=null;
      }
      this.setText('guard-reserve-value',validReserve?format(reserve,0,' %'):'Nicht konfiguriert');
      this.renderForecast();
    }
    async sendReserve(value){
      const e=this.entities.reserve;
      if(!e||!e.startsWith('input_number.')||this.value('reserve')===null||this.reservePending){
        this.setText('bcg-save-feedback','Keine beschreibbare HA-Reserve-Entität konfiguriert.');return;
      }
      if(!Number.isInteger(value)||value<8||value>30){this.setText('bcg-save-feedback','Ungültiger Reservewert.');return;}
      this.reservePending=true;this.requestedReserve=value;this.renderHass();
      this.setText('bcg-save-feedback','Reserve wird an Home Assistant gesendet …');
      try{
        await this._hass.callService('input_number','set_value',{entity_id:e,value});
        this.setText('bcg-save-feedback','An Home Assistant gesendet; tatsächliche Übernahme und Guard-Wirkung separat prüfen.');
      }catch(err){
        this.setText('bcg-save-feedback','Speichern fehlgeschlagen; keine Übernahme bestätigt.');
        console.warn('Battery Control Guard: reserve save rejected',String(err));
      }finally{this.reservePending=false;this.renderHass();}
    }
    async readJson(key,force){
      const now=Date.now(),interval=key==='status'?12000:90000;
      const last=key==='status'?this.lastStatus:this.lastForecast;
      if(!force&&now-last<interval)return;
      if(key==='status')this.lastStatus=now;else this.lastForecast=now;
      try{
        const resp=await fetch(this.urls[key]+'?v='+now,{cache:'no-store',credentials:'same-origin'});
        if(!resp.ok)throw Error('HTTP '+resp.status);
        const payload=await resp.json();
        if(key==='status'){
          if(!validStatus(payload))throw Error('status stale or invalid');
          this.status=payload;this.renderStatus();
        }else{
          if(!validForecast(payload))throw Error('forecast stale or invalid');
          this.forecast=payload;this.renderForecast();
        }
      }catch(err){
        if(key==='status'){this.status=null;this.renderStatus();}
        else{this.forecast=null;this.renderForecast();}
        console.warn('Battery Control Guard '+key+' unavailable:',String(err));
      }
    }
    async refresh(force=false){
      if(this.working)return;this.working=true;
      try{await Promise.all([this.readJson('status',force),this.readJson('forecast',force)]);}
      finally{this.working=false;this.renderHass();}
    }
    renderStatus(){
      const v=validStatus(this.status)?this.status:null;
      this.setText('guard-mode-version',v?'('+v.version+')':'(Status unbekannt)');
      if(!v){
        for(const key of ['active','would','potential','ledger','recovery','reserve','age'])this.setText('guard-v070-'+key,'—');
        this.setText('guard-v070-reason','Keine gültigen aktuellen Controllerdaten. Keine Zusatzfreigabe bestätigt.');
        this.setText('guard-v070-update','Status unbekannt oder abgelaufen');
        this.setText('bcg-diagnostics','Keine aktuellen gültigen Statusdaten.');
        return;
      }
      this.setText('guard-v070-active',v.permissionActive===true?'JA':'NEIN');
      this.setText('guard-v070-would',v.wouldGrantIfPlanned===true?'JA':'NEIN');
      this.setText('guard-v070-potential',format(v.potentialBudgetKwh,2,' kWh'));
      this.setText('guard-v070-ledger',format(v.spentKwh,2,' kWh')+' / '+format(v.remainingKwh,2,' kWh'));
      const dt=Number.isFinite(Date.parse(v.recoveryAt))?new Date(v.recoveryAt):null;
      this.setText('guard-v070-recovery',dt?dt.toLocaleString('de-DE',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'Nicht gesichert');
      this.setText('guard-v070-reserve',format(v.haReservePct,1,' %'));
      this.setText('guard-v070-age',format(v.forecastAgeSeconds==null?null:Math.round(v.forecastAgeSeconds/60),0,' min'));
      const plan=v.planConfigured&&Number.isFinite(Date.parse(v.planTime))
        ? ' · Ladeziel '+(v.planTargetSoc??'—')+' % bis '+new Date(v.planTime).toLocaleString('de-DE',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})
        : '';
      this.setText('guard-v070-reason',(REASONS[v.reasonCode]||String(v.reasonCode||'Status unbekannt'))+plan);
      this.setText('guard-v070-update','Aktualisiert '+new Date(v.generatedAt).toLocaleTimeString('de-DE')+' · Modellvorschau ist keine reale Freigabe.');
      this.setText('bcg-diagnostics','Version: '+v.version+'\nGrund: '+String(v.reasonCode||'—')+'\nDaten kohärent: '+String(v.dataCoherent??'unbekannt')+'\nControllerphase: '+String(v.controllerPhase??'—')+'\nQuellenstatus: gültig bis '+v.validUntil);
      this.renderHass();
    }
    renderForecast(){
      const p=validForecast(this.forecast)?this.forecast:null;
      if(!p){this.setText('guard-int-plan','—');this.setText('guard-int-budget','—');
        this.setText('guard-int-plan-note','Keine gültige aktuelle Beobachtungsprognose.');return;}
      const f=p.forecast||{};
      const trough=f.projectedTroughSocPct,cap=p.capacityKwh,uncertainty=f.uncertaintyAllowanceKwh;
      const haReserve=this.value('reserve');
      const statusReserve=validStatus(this.status)?this.status.haReservePct:null;
      const floor=haReserve!==null?haReserve:statusReserve;
      if([trough,cap,uncertainty,floor].some(n=>n===null||n===undefined||!Number.isFinite(Number(n)))||Number(cap)<=0){
        this.setText('guard-int-plan','—');this.setText('guard-int-budget','—');
        this.setText('guard-int-plan-note','Prognose oder wirksame Sicherheitsreserve unvollständig.');return;
      }
      const budget=Math.max(0,((Number(trough)-Number(floor))/100)*Number(cap)-Number(uncertainty));
      this.setText('guard-int-plan',format(trough,1,' %'));
      this.setText('guard-int-budget',format(budget,2,' kWh'));
      const when=Number.isFinite(Date.parse(f.recoveryAt))?new Date(f.recoveryAt).toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit'}):'nicht gesichert';
      this.setText('guard-int-plan-note','PV-Erholung ca. '+when+' · Berechnung nur zur Anzeige, keine Freigabe.');
    }
    async mountHistory(){
      const target=this.shadowRoot.getElementById('guardtrend');
      if(!target)return;
      const a=this.entities.history_soc||this.entities.battery_soc;
      const b=this.entities.history_min_soc||this.entities.kostal_min_soc;
      if(!a||!b){target.textContent='Verlauf: HA-Entitäten history_soc und history_min_soc zuordnen.';return;}
      try{
        if(typeof window.loadCardHelpers!=='function')throw Error('Lovelace card helpers unavailable');
        const h=await window.loadCardHelpers();
        if(!this.isConnected||!target.isConnected)return;
        const card=h.createCardElement({type:'history-graph',title:'Hausakku und Mindest-SoC · 48 Stunden',hours_to_show:48,
          refresh_interval:120,entities:[{entity:a,name:'Hausakku-SoC'},{entity:b,name:'KOSTAL Mindest-SoC'}]});
        if(this._hass)card.hass=this._hass;
        this.historyCard=card;target.replaceChildren(card);
      }catch(err){target.textContent='Verlauf derzeit nicht verfügbar.';console.warn('Guard history:',String(err));}
    }
  }
  function validStatus(p){
    if(!p||p.schema!==1||typeof p.version!=='string'||!/^0\.8\./.test(p.version)||typeof p.permissionActive!=='boolean')return false;
    const created=Date.parse(p.generatedAt),until=Date.parse(p.validUntil),now=Date.now();
    return Number.isFinite(created)&&Number.isFinite(until)&&created<=now+5000&&created>=now-60000&&until>now&&until<=now+70000;
  }
  function validForecast(p){
    if(!p||p.schema!==3||typeof p.version!=='string'||!/^0\.8\./.test(p.version)||p.mode!=='observe_only'||p.eligibleForControl!==false)return false;
    const at=Date.parse(p.asOf),now=Date.now();
    return Number.isFinite(at)&&at<=now+5000&&at>=now-20*60000;
  }
  if(!customElements.get('battery-control-guard-card'))
    customElements.define('battery-control-guard-card',BatteryControlGuardCard);
})();