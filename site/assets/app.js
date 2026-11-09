const DATA = { jobs: [], status: {}, sources: [], candidates: [], markets: {} };
const localDate = (value) => {
  if (!value) return '';
  if (/^\d{4}-\d{2}-\d{2}$/.test(String(value))) {
    const [year, month, day] = String(value).split('-').map(Number);
    return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(new Date(Date.UTC(year, month - 1, day)));
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(date);
};
const text = (value) => (value == null ? '' : String(value)).trim();
const truthy = (value) => ['true', '1', 'yes', 'y'].includes(text(value).toLowerCase());
const safeUrl = (value) => {
  if (!text(value)) return '';
  try {
    const url = new URL(value, window.location.href);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
  } catch { return ''; }
};
const escapeHtml = (value) => text(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);

function parseCsv(csv) {
  const records = [];
  let row = [], cell = '', quoted = false;
  for (let i = 0; i < csv.length; i += 1) {
    const char = csv[i];
    if (quoted && char === '"' && csv[i + 1] === '"') { cell += '"'; i += 1; }
    else if (char === '"') quoted = !quoted;
    else if (!quoted && char === ',') { row.push(cell); cell = ''; }
    else if (!quoted && (char === '\n' || char === '\r')) {
      if (char === '\r' && csv[i + 1] === '\n') i += 1;
      row.push(cell); cell = '';
      if (row.some((part) => part !== '')) records.push(row);
      row = [];
    } else cell += char;
  }
  if (cell !== '' || row.length) { row.push(cell); records.push(row); }
  if (!records.length) return [];
  const headers = records.shift().map((header) => header.trim());
  return records.map((values) => Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ''])));
}

async function fetchData() {
  const results = await Promise.allSettled([
    fetch('./data/history.csv', { cache: 'no-store' }).then((response) => { if (!response.ok) throw new Error('history'); return response.text(); }),
    fetch('./data/status.json', { cache: 'no-store' }).then((response) => { if (!response.ok) throw new Error('status'); return response.json(); }),
    fetch('./config/sources.json', { cache: 'no-store' }).then((response) => { if (!response.ok) throw new Error('sources'); return response.json(); })
  ]);
  if (results[0].status === 'fulfilled') DATA.jobs = parseCsv(results[0].value);
  if (results[1].status === 'fulfilled') DATA.status = results[1].value;
  if (results[2].status === 'fulfilled') {
    DATA.sources = results[2].value.sources || [];
    DATA.candidates = results[2].value.discovery_candidates || [];
    DATA.markets = results[2].value.markets || {};
    DATA.financeTerms = results[2].value.finance_title_terms || [];
  }
  const failed = results.some((result) => result.status === 'rejected');
  if (failed) showNotice('Some job data could not be loaded. If you are offline, reconnect to refresh the latest postings.');
  return DATA;
}

function showNotice(message) {
  const notice = document.getElementById('data-notice');
  if (!notice) return;
  notice.hidden = false;
  notice.textContent = message;
}

function roleMatch(job) {
  if (text(job.in_role)) return truthy(job.in_role);
  const title = text(job.title).toLowerCase();
  return (DATA.financeTerms || []).some((term) => {
    const escaped = term.toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return new RegExp(`\\b${escaped}\\b`, 'i').test(title);
  });
}

function marketFor(job) {
  const location = text(job.location).toLowerCase();
  for (const [id, market] of Object.entries(DATA.markets)) {
    const cityHit = (market.cities || []).some((city) => location.includes(city.toLowerCase()));
    if (cityHit) return id;
  }
  if (/\b(remote|work from home)\b/.test(location)) {
    if (/\b(oklahoma|ok)\b/.test(location)) return 'tulsa_ok';
    if (/\b(arkansas|ar)\b/.test(location)) return 'northwest_ar';
  }
  return '';
}

function isOpen(job) {
  const status = text(job.status).toLowerCase();
  return !['removed', 'closed', 'inactive', 'expired'].includes(status) && !text(job.removed_date);
}

function localJobs() { return DATA.jobs.filter((job) => Boolean(marketFor(job))); }
function marketLabel(id) { return id === 'tulsa_ok' ? 'Tulsa area' : id === 'northwest_ar' ? 'Northwest Arkansas' : 'Regional'; }
function runDay() { return text(DATA.status.run_time).slice(0, 10); }
function newestFirst(a, b) { return (text(b.posted_date || b.first_seen)).localeCompare(text(a.posted_date || a.first_seen)); }

function jobLink(job, compact = false) {
  const href = safeUrl(job.url);
  const card = document.createElement(href ? 'a' : 'article');
  card.className = compact ? 'job-row' : 'job-card';
  if (href) { card.href = href; card.target = '_blank'; card.rel = 'noopener noreferrer'; }
  const market = marketLabel(marketFor(job));
  const role = roleMatch(job);
  const status = isOpen(job) ? 'Open' : 'Removed';
  if (compact) {
    card.innerHTML = `<span><span class="job-title">${escapeHtml(job.title || 'Untitled role')}</span><span class="job-company">${escapeHtml(job.employer || 'Employer')} · ${escapeHtml(job.location || market)}</span></span><span class="job-meta">${escapeHtml(localDate(job.posted_date || job.first_seen))}<span>${escapeHtml(market)}</span></span>`;
  } else {
    card.innerHTML = `<div class="job-card-top"><span class="job-badge ${isOpen(job) ? '' : 'removed'}">${status}${role ? ' · Finance match' : ''}</span><span class="job-date">${escapeHtml(localDate(job.posted_date || job.first_seen))}</span></div><span class="job-title">${escapeHtml(job.title || 'Untitled role')}</span><span class="job-company">${escapeHtml(job.employer || 'Employer')}</span><div class="job-card-bottom"><span>${escapeHtml(job.location || market)}</span><span>${href ? 'View posting ↗' : 'No posting link'}</span></div>`;
  }
  return card;
}

function emptyState(title, message, linkText = 'Browse employer boards', linkHref = './browse.html') {
  const div = document.createElement('div');
  div.className = 'empty-state';
  div.innerHTML = `<strong>${escapeHtml(title)}</strong>${escapeHtml(message)} <a href="${linkHref}">${escapeHtml(linkText)} →</a>`;
  return div;
}

function sourceCard(source) {
  const href = safeUrl(source.career_url);
  const card = document.createElement(href ? 'a' : 'div');
  const pending = Boolean(source.status);
  card.className = `source-card${pending ? ' source-card-pending' : ''}`;
  if (href) { card.href = href; card.target = '_blank'; card.rel = 'noopener noreferrer'; }
  const label = source.board_name ? `${source.employer} · ${source.board_name}` : source.employer;
  const state = pending ? '<span class="source-status">DISCOVERY</span>' : '';
  card.innerHTML = `<strong>${escapeHtml(label)}</strong><span class="source-card-meta">${state}<span class="source-arrow" aria-hidden="true">↗</span></span>`;
  return card;
}

function renderFooter() {
  const status = document.getElementById('footer-data-state');
  if (!status) return;
  status.textContent = DATA.status.run_time ? `Last data run: ${localDate(DATA.status.run_time)}` : 'Waiting for the first successful data run.';
  const updated = document.getElementById('last-updated');
  if (updated) updated.textContent = DATA.status.run_time ? `Last run · ${localDate(DATA.status.run_time)}` : 'Awaiting first data run';
  if (!DATA.status.run_time && !DATA.jobs.length) showNotice('The site is published. Listings will appear after the collector completes its first successful run.');
}

function renderToday() {
  const regional = localJobs();
  const active = regional.filter((job) => isOpen(job) && roleMatch(job));
  const day = runDay();
  const fresh = active.filter((job) => (text(job.first_seen) || text(job.posted_date)).slice(0, 10) === day);
  const removed = regional.filter((job) => !isOpen(job) && roleMatch(job) && text(job.removed_date).slice(0, 10) === day);
  const values = { 'metric-open': active.length, 'metric-new': fresh.length, 'metric-removed': removed.length, 'metric-sources': DATA.sources.length };
  for (const [id, value] of Object.entries(values)) { const node = document.getElementById(id); if (node) node.textContent = String(value); }
  const heroSourceCount = document.getElementById('hero-source-count');
  if (heroSourceCount) heroSourceCount.textContent = String(DATA.sources.length);
  const list = document.getElementById('today-list');
  if (list) {
    list.replaceChildren();
    const jobs = fresh.length ? fresh.sort(newestFirst) : active.slice().sort(newestFirst).slice(0, 4);
    if (!jobs.length) list.append(emptyState('No local postings yet', 'The site is ready. Once the collector starts, new finance roles will appear here.', 'Explore employers', './browse.html'));
    else jobs.slice(0, 5).forEach((job) => list.append(jobLink(job, true)));
  }
  const sources = document.getElementById('source-cards');
  if (sources) { sources.replaceChildren(); [...DATA.sources, ...DATA.candidates].forEach((source) => sources.append(sourceCard(source))); }
}

function renderBrowse() {
  const query = document.getElementById('job-search');
  const market = document.getElementById('market-filter');
  const status = document.getElementById('status-filter');
  const finance = document.getElementById('finance-only');
  const results = document.getElementById('job-results');
  const count = document.getElementById('result-count');
  if (!results) return;
  const params = new URLSearchParams(window.location.search);
  if (['tulsa_ok', 'northwest_ar'].includes(params.get('market'))) market.value = params.get('market');
  const draw = () => {
    let jobs = localJobs();
    if (market.value !== 'all') jobs = jobs.filter((job) => marketFor(job) === market.value);
    if (status.value === 'open') jobs = jobs.filter(isOpen);
    if (status.value === 'removed') jobs = jobs.filter((job) => !isOpen(job));
    if (finance.checked) jobs = jobs.filter(roleMatch);
    const q = text(query.value).toLowerCase();
    if (q) jobs = jobs.filter((job) => [job.title, job.employer, job.location, job.department].some((field) => text(field).toLowerCase().includes(q)));
    jobs.sort(newestFirst);
    count.textContent = `${jobs.length} ${finance.checked ? 'finance ' : ''}listing${jobs.length === 1 ? '' : 's'} · ${market.value === 'all' ? 'all markets' : marketLabel(market.value)}`;
    results.replaceChildren();
    if (!jobs.length) results.append(emptyState(DATA.jobs.length ? 'No matching jobs found' : 'Job history is not populated yet', DATA.jobs.length ? 'Try another market or remove a filter.' : 'The daily collector will populate this list after its first successful run.', 'Open employer boards', '#browse-source-links'));
    else jobs.forEach((job) => results.append(jobLink(job)));
  };
  [query, market, status, finance].forEach((input) => input.addEventListener(input === query ? 'input' : 'change', draw));
  document.getElementById('clear-filters')?.addEventListener('click', () => { query.value = ''; market.value = 'all'; status.value = 'open'; finance.checked = true; draw(); query.focus(); });
  draw();
  const links = document.getElementById('browse-source-links');
  if (links) {
    links.replaceChildren();
    [...DATA.sources, ...DATA.candidates].forEach((source) => {
      const href = safeUrl(source.career_url);
      if (!href) return;
      const a = document.createElement('a'); a.className = 'source-pill'; a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer';
      a.innerHTML = `${escapeHtml(source.employer)} <span aria-hidden="true">↗</span>`;
      links.append(a);
    });
  }
}

function renderMarketCard(id, title, cityDescription, featured = false) {
  const jobs = localJobs().filter((job) => marketFor(job) === id && isOpen(job) && roleMatch(job));
  const byEmployer = new Map();
  jobs.forEach((job) => byEmployer.set(text(job.employer) || 'Other employers', (byEmployer.get(text(job.employer) || 'Other employers') || 0) + 1));
  const top = [...byEmployer.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
  const max = top.length ? top[0][1] : 1;
  const chart = top.length ? top.map(([name, value]) => `<div class="bar-row"><span class="bar-name">${escapeHtml(name)}</span><span class="bar-track"><span class="bar-fill" style="display:block;width:${Math.max(6, value / max * 100)}%"></span></span><span class="bar-number">${value}</span></div>`).join('') : '<div class="loading-state">Employer counts will appear after the first data run.</div>';
  const sourceCount = DATA.sources.filter((source) => (source.markets || []).includes(id)).length;
  const section = document.createElement('article');
  section.className = `market-card${featured ? ' featured' : ''}`;
  const totalLabel = DATA.status.run_time ? 'open finance matches' : 'awaiting first data run';
  section.innerHTML = `<div class="market-cities" aria-hidden="true">${id === 'tulsa_ok' ? 'TUL' : 'NWA'}</div><div class="market-card-head"><div><p class="eyebrow">${id === 'tulsa_ok' ? 'OKLAHOMA' : 'ARKANSAS'}</p><h2>${escapeHtml(title)}</h2><p class="market-count-label">${escapeHtml(cityDescription)}</p></div><span class="market-index">0${featured ? '1' : '2'}</span></div><div class="market-big-number">${DATA.status.run_time ? jobs.length : '—'}</div><p class="market-count-label">${totalLabel}</p><div class="market-chart">${chart}</div><div class="market-card-footer"><span>${sourceCount} employer boards</span><a class="text-link${featured ? ' light-link' : ''}" href="./browse.html?market=${id}">Browse market →</a></div>`;
  return section;
}

function renderMarket() {
  const grid = document.getElementById('market-grid');
  if (grid) {
    grid.replaceChildren();
    grid.append(renderMarketCard('tulsa_ok', 'Tulsa area', 'Tulsa · Broken Arrow · Tahlequah · Bartlesville', true));
    grid.append(renderMarketCard('northwest_ar', 'Northwest Arkansas', 'Bentonville · Fayetteville · Springdale'));
  }
  const sources = document.getElementById('market-source-list');
  if (sources) {
    sources.replaceChildren();
    DATA.sources.forEach((source) => {
      const href = safeUrl(source.career_url);
      const card = document.createElement(href ? 'a' : 'div'); card.className = 'market-source';
      if (href) { card.href = href; card.target = '_blank'; card.rel = 'noopener noreferrer'; }
      const names = (source.markets || []).map(marketLabel).join(' + ');
      card.innerHTML = `<strong>${escapeHtml(source.employer)}</strong><span>${escapeHtml(names)}</span>`;
      sources.append(card);
    });
  }
  const count = document.getElementById('market-source-count');
  if (count) count.textContent = `${DATA.sources.length} active boards · ${DATA.candidates.length} to validate`;
}

async function start() {
  await fetchData();
  renderFooter();
  const page = document.body.dataset.page;
  if (page === 'today') renderToday();
  if (page === 'browse') renderBrowse();
  if (page === 'market') renderMarket();
  if ('serviceWorker' in navigator && location.protocol.startsWith('http')) navigator.serviceWorker.register('./sw.js').catch(() => {});
}

start();
