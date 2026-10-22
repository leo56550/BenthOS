/* ── Carte Leaflet — Planification de déploiement KOSMOS ───────────────── */

var map = L.map('map', { zoomControl: true }).setView([47.5, -3.5], 9);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  maxZoom: 19
}).addTo(map);

/* ── Tooltip coordonnées ────────────────────────────────────────────────── */
var tip = document.getElementById('coord-tip');

map.on('mousemove', function (e) {
  tip.style.display = 'block';
  tip.style.left = (e.originalEvent.clientX + 14) + 'px';
  tip.style.top  = (e.originalEvent.clientY - 30) + 'px';
  tip.textContent = e.latlng.lat.toFixed(6) + ',  ' + e.latlng.lng.toFixed(6);
});

map.on('mouseout', function () { tip.style.display = 'none'; });

/* ── Marqueurs numérotés (waypoints utilisateur) ────────────────────────── */
var markers = [];

/* ── Marqueurs infoStation (points de référence, orange) ────────────────── */
var infoMarkers = [];

/* ── Palette par année ───────────────────────────────────────────────────── */
var _YEAR_PALETTE = [
  { bg: '#e68c14', border: '#f5c842' },  // orange
  { bg: '#16a0a0', border: '#4fd4d4' },  // teal
  { bg: '#9B59B6', border: '#c39bd3' },  // violet
  { bg: '#27AE60', border: '#82e0aa' },  // vert
  { bg: '#C0392B', border: '#e57373' },  // rouge
  { bg: '#E91E63', border: '#f48fb1' },  // rose
  { bg: '#795548', border: '#bcaaa4' },  // brun
  { bg: '#607D8B', border: '#90a4ae' },  // bleu-gris
];
var _yearColorMap  = {};   // { "2025": {bg, border}, ... }
var _yearColorIdx  = 0;

function _yearColor(year) {
  if (!year) return { bg: '#556677', border: '#7ec8e3' };
  if (!_yearColorMap[year]) {
    _yearColorMap[year] = _YEAR_PALETTE[_yearColorIdx % _YEAR_PALETTE.length];
    _yearColorIdx++;
    _refreshLegend();
  }
  return _yearColorMap[year];
}

function _extractYear(dateStr) {
  if (!dateStr) return null;
  var s = String(dateStr).trim();
  var parts = s.split('/');
  if (parts.length === 3 && parts[2].length === 4) return parts[2];
  if (s.length >= 4 && s[4] === '-') return s.substring(0, 4);
  if (/^\d{8}$/.test(s)) return s.substring(0, 4);
  if (/^\d{6}$/.test(s)) return '20' + s.substring(0, 2);
  return null;
}

function _refreshLegend() {
  var leg = document.getElementById('legend');
  if (!leg) return;
  var years = Object.keys(_yearColorMap);
  if (years.length === 0) { leg.style.display = 'none'; return; }
  var html = '<div style="font-weight:bold;margin-bottom:5px;color:#F2BFB4;">Légende</div>';
  years.sort().forEach(function(y) {
    var c = _yearColorMap[y];
    html += '<div style="display:flex;align-items:center;gap:7px;margin:3px 0;">'
          + '<span style="display:inline-block;width:16px;height:16px;border-radius:50%;'
          + 'background:' + c.bg + ';border:2px solid ' + c.border + ';flex-shrink:0;"></span>'
          + '<span>' + y + '</span></div>';
  });
  html += '<div style="display:flex;align-items:center;gap:7px;margin:3px 0;">'
        + '<span style="display:inline-block;width:16px;height:16px;border-radius:50%;'
        + 'background:#2778a2;border:2px solid #7ec8e3;flex-shrink:0;"></span>'
        + '<span style="color:#7ec8e3;">Ajoutés</span></div>';
  leg.innerHTML  = html;
  leg.style.display = 'block';
}

function _infoIcon(code) {
  return L.divIcon({
    className: '',
    html: '<div style="background:#e68c14;color:#fff;border:2px solid #f5a623;'
        + 'border-radius:50%;min-width:26px;height:26px;line-height:22px;'
        + 'text-align:center;font:bold 9px sans-serif;padding:0 4px;'
        + 'box-shadow:0 2px 6px #0008;white-space:nowrap;">'
        + code + '</div>',
    iconSize: null, iconAnchor: [13, 13], popupAnchor: [0, -16]
  });
}

function _importedIcon(txt, bg, border) {
  return L.divIcon({
    className: '',
    html: '<div style="background:' + (bg||'#16a0a0') + ';color:#fff;'
        + 'border:2px solid ' + (border||'#4fd4d4') + ';'
        + 'border-radius:50%;min-width:26px;height:26px;line-height:22px;'
        + 'text-align:center;font:bold 11px sans-serif;padding:0 4px;'
        + 'box-shadow:0 2px 6px #0008;white-space:nowrap;">'
        + txt + '</div>',
    iconSize: null, iconAnchor: [13, 13], popupAnchor: [0, -16]
  });
}

function loadInfostationPoints(data) {
  clearInfostationMarkers();
  var points = data;
  if (typeof data === 'string') {
    try { points = JSON.parse(data); } catch(e) { return; }
  }
  if (!Array.isArray(points)) { return; }
  points.forEach(function (p) {
    if (p.lat == null || p.lng == null) return;
    var m = L.marker([p.lat, p.lng], { icon: _infoIcon(p.code || '?') })
             .addTo(map)
             .bindPopup(
               '<b>' + (p.code || '') + '</b>'
               + (p.nom  ? '<br>' + p.nom  : '')
               + (p.date ? '<br>' + p.date : '')
               + '<br><span style="color:#aaa;font-size:11px;">'
               + p.lat.toFixed(6) + ',&nbsp;' + p.lng.toFixed(6) + '</span>'
             );
    infoMarkers.push(m);
  });
  if (infoMarkers.length > 0) {
    var group = L.featureGroup(infoMarkers);
    map.fitBounds(group.getBounds().pad(0.15));
  }
}

function clearInfostationMarkers() {
  infoMarkers.forEach(function (m) { map.removeLayer(m); });
  infoMarkers = [];
}

function loadImportedPoints(data) {
  var points = data;
  if (typeof data === 'string') {
    try { points = JSON.parse(data); } catch(e) { return; }
  }
  if (!Array.isArray(points)) { return; }
  points.forEach(function (p) {
    if (p.lat == null || p.lng == null) return;
    var idx   = markers.length;
    var label = p.nom || p.code || ('Point ' + (idx + 1));
    var iconTxt = p.nom || String(idx + 1);
    var year  = _extractYear(p.date);
    var clr   = _yearColor(year);
    var m = L.marker([p.lat, p.lng], { icon: _importedIcon(iconTxt, clr.bg, clr.border) })
             .addTo(map)
             .bindPopup(
               '<b>' + label + '</b><br>'
               + p.lat.toFixed(6) + ',&nbsp;' + p.lng.toFixed(6)
               + (p.date ? '<br><span style="color:#aaa;font-size:11px;">' + p.date + '</span>' : '')
             );
    markers.push(m);
    if (bridge) {
      bridge.onPointAdded(JSON.stringify({
        index: idx, lat: p.lat, lng: p.lng, label: label, date: p.date || '',
        source: 'imported', iconTxt: iconTxt
      }));
    }
  });
}

function rebuildMarkers(data) {
  clearAllMarkers();
  _yearColorMap = {};
  _yearColorIdx = 0;
  var points = typeof data === 'string' ? JSON.parse(data) : data;
  points.forEach(function (p, i) {
    var lbl     = p.label || ('Point ' + (i + 1));
    var iconTxt = p.iconTxt || lbl;
    var m;
    if (p.source === 'imported') {
      var clr = _yearColor(_extractYear(p.date));
      m = L.marker([p.lat, p.lng], { icon: _importedIcon(iconTxt, clr.bg, clr.border) })
           .addTo(map)
           .bindPopup('<b>' + lbl + '</b><br>'
             + Number(p.lat).toFixed(6) + ',&nbsp;' + Number(p.lng).toFixed(6)
             + (p.date ? '<br><span style="color:#aaa;font-size:11px;">' + p.date + '</span>' : ''));
    } else {
      m = L.marker([p.lat, p.lng], { icon: _icon(i + 1, lbl) })
           .addTo(map)
           .bindPopup('<b>' + lbl + '</b><br>'
             + Number(p.lat).toFixed(6) + ', ' + Number(p.lng).toFixed(6));
    }
    markers.push(m);
  });
  _refreshLegend();
}

function _icon(n, label) {
  var text = label || String(n);
  return L.divIcon({
    className: '',
    html: '<div style="background:#2778a2;color:#fff;border:2px solid #7ec8e3;'
        + 'border-radius:50%;min-width:26px;height:26px;line-height:22px;'
        + 'text-align:center;font:bold 11px sans-serif;padding:0 4px;'
        + 'box-shadow:0 2px 6px #0008;white-space:nowrap;">'
        + n + '</div>',
    iconSize: null, iconAnchor: [13, 13], popupAnchor: [0, -16]
  });
}

function _updateMarkerPopup(m, label) {
  m.setPopupContent(
    '<b>' + label + '</b><br>'
    + m.getLatLng().lat.toFixed(6) + ', ' + m.getLatLng().lng.toFixed(6)
  );
}

/* ── Pont Qt WebChannel ─────────────────────────────────────────────────── */
var bridge = null;

new QWebChannel(qt.webChannelTransport, function (ch) {
  bridge = ch.objects.planBridge;
});

/* ── API publique (appelée depuis Python via runJavaScript) ─────────────── */

function updateMarkerLabel(idx, label) {
  if (idx < 0 || idx >= markers.length) return;
  var m = markers[idx];
  m.setIcon(_icon(idx + 1, label));
  _updateMarkerPopup(m, label);
}

function removeMarkerByIndex(idx) {
  if (idx < 0 || idx >= markers.length) return;
  map.removeLayer(markers[idx]);
  markers.splice(idx, 1);
  markers.forEach(function (m, i) {
    m.setIcon(_icon(i + 1));
    _updateMarkerPopup(m, 'Point ' + (i + 1));
  });
}

function clearAllMarkers() {
  markers.forEach(function (m) { map.removeLayer(m); });
  markers = [];
}

function addWaypointAtCoords(lat, lng, label) {
  var idx = markers.length;
  var lbl = label || ('Point ' + (idx + 1));
  var m = L.marker([lat, lng], { icon: _icon(idx + 1, lbl) })
           .addTo(map)
           .bindPopup('<b>' + lbl + '</b><br>'
             + lat.toFixed(6) + ',&nbsp;' + lng.toFixed(6));
  markers.push(m);
  if (bridge) {
    bridge.onPointAdded(JSON.stringify({
      index: idx, lat: lat, lng: lng, label: lbl,
      source: 'manual', iconTxt: String(idx + 1)
    }));
  }
  map.setView([lat, lng], Math.max(map.getZoom(), 12));
  _refreshLegend();
}

/* ── Clic sur la carte → ajout d'un waypoint ───────────────────────────── */
map.on('click', function (e) {
  var lat = e.latlng.lat, lng = e.latlng.lng;
  var idx = markers.length;
  var defaultLabel = 'Point ' + (idx + 1);

  var m = L.marker([lat, lng], { icon: _icon(idx + 1) })
           .addTo(map)
           .bindPopup('<b>' + defaultLabel + '</b><br>'
             + lat.toFixed(6) + ', ' + lng.toFixed(6));
  markers.push(m);

  if (bridge) {
    bridge.onPointAdded(JSON.stringify({
      index: idx, lat: lat.toFixed(6), lng: lng.toFixed(6),
      label: defaultLabel, source: 'manual', iconTxt: String(idx + 1)
    }));
  }
  _refreshLegend();
});
