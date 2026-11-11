const DATA = { jobs: [], archiveJobs: [], status: {}, sources: [], supplementalSources: [], candidates: [], markets: {}, financeTerms: [] };
const SHORTLIST_KEY = 'ledgerline-job-watcher-shortlist-v1';

const text = (value) => (value == null ? '' : String(value)).trim();
const truthy = (value) => ['true', '1', 'yes', 'y'].includes(text(value).toLowerCase());
const escapeHtml = (value) => text(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
const safeUrl = (value) => {
  if (!text(value)) return '';
  try {
    const url = new URL(value, window.location.href);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
  } catch { return ''; }
};

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
    fetch('./config/sources.json', { cache: 'no-store' }).then((response) => { if (!response.ok) throw new Error('sources'); return response.json(); }),
    fetch('./data/archive/history.csv', { cache: 'no-store' }).then((response) => { if (!response.ok) throw new Error('archive'); return response.text(); })
  ]);
  if (results[0].status === 'fulfilled') DATA.jobs = parseCsv(results[0].value);
  if (results[1].status === 'fulfilled') DATA.status = results[1].value;
  if (results[2].status === 'fulfilled') {
    const config = results[2].value;
    DATA.sources = config.sources || [];
    DATA.supplementalSources = config.supplemental_sources || [];
    DATA.candidates = config.discovery_candidates || [];
    DATA.markets = config.markets || {};
    DATA.financeTerms = config.finance_title_terms || [];
  }
  if (results[3].status === 'fulfilled') DATA.archiveJobs = parseCsv(results[3].value);
  if (results.some((result) => result.status === 'rejected')) {
    showNotice('Some job data could not be loaded. If you are offline, reconnect to refresh the latest postings.');
  }
  return DATA;
}

function showNotice(message) {
  const notice = document.getElementById('data-notice');
  if (!notice) return;
  notice.hidden = false;
  notice.textContent = message;
}

function dateOnly(value) {
  const match = text(value).match(/^(\d{4}-\d{2}-\d{2})/);
  return match ? match[1] : '';
}

function localDate(value) {
  const day = dateOnly(value);
  if (!day) return text(value);
  const [year, month, date] = day.split('-').map(Number);
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(new Date(Date.UTC(year, month - 1, date)));
}

function localDateTime(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return text(value);
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short'
  }).format(parsed);
}

function utcToday() { return new Date().toISOString().slice(0, 10); }
function runDay() { return dateOnly(DATA.status.run_date || DATA.status.run_time) || utcToday(); }

function daysBetween(start, end) {
  const a = dateOnly(start), b = dateOnly(end);
  if (!a || !b) return null;
  const [ay, am, ad] = a.split('-').map(Number);
  const [by, bm, bd] = b.split('-').map(Number);
  return Math.floor((Date.UTC(by, bm - 1, bd) - Date.UTC(ay, am - 1, ad)) / 86400000);
}

function roleMatch(job) {
  if (text(job.in_role)) return truthy(job.in_role);
  const title = text(job.title).toLowerCase();
  return DATA.financeTerms.some((term) => {
    const escaped = term.toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return new RegExp(`\\b${escaped}\\b`, 'i').test(title);
  });
}

function marketIdsFor(job) {
  if (text(job.market)) return text(job.market).split(';').filter(Boolean);
  const location = text(job.location).toLowerCase();
  const ids = [];
  for (const [id, market] of Object.entries(DATA.markets)) {
    if ((market.cities || []).some((city) => {
      const escaped = text(city).toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      return new RegExp(`(^|[^a-z0-9_])${escaped}([^a-z0-9_]|$)`, 'i').test(location);
    })) ids.push(id);
  }
  if (!ids.length && /\b(remote|work from home)\b/.test(location)) {
    if (/\b(oklahoma|ok)\b/.test(location) && DATA.markets.tulsa_ok) ids.push('tulsa_ok');
    if (/\b(arkansas|ar)\b/.test(location) && DATA.markets.northwest_ar) ids.push('northwest_ar');
  }
  return ids;
}

function marketFor(job) { return marketIdsFor(job)[0] || ''; }
function marketLabel(id) { return id === 'tulsa_ok' ? 'Tulsa area' : id === 'northwest_ar' ? 'Northwest Arkansas' : 'Other / not specified'; }

function isOpen(job) {
  const status = text(job.status).toLowerCase();
  return !['removed', 'closed', 'inactive', 'expired', 'archived'].includes(status) && !text(job.removed_date);
}

function isArchived(job) { return text(job.status).toLowerCase() === 'archived'; }

function applicationUrl(job) {
  const direct = safeUrl(job.url);
  if (direct) return direct;
  const sourceId = text(job.posting_id).split(':', 1)[0];
  const source = DATA.sources.find((item) => item.id === sourceId);
  return safeUrl(source && source.career_url);
}

function jobRow(job) {
  const href = applicationUrl(job);
  const row = document.createElement(href ? 'a' : 'article');
  row.className = 'job-row';
  if (href) { row.href = href; row.target = '_blank'; row.rel = 'noopener noreferrer'; }
  const market = marketIdsFor(job).map(marketLabel).join(' + ') || 'Location not classified';
  row.innerHTML = `<span><span class="job-title">${escapeHtml(job.title || 'Untitled role')}</span><span class="job-company">${escapeHtml(job.employer || 'Employer')} · ${escapeHtml(job.location || market)}</span></span><span class="job-meta">${escapeHtml(localDate(job.posted_date || job.first_seen))}<span>${escapeHtml(market)}</span></span>`;
  return row;
}

function jobCard(job, shortlist, beyondLocal = false) {
  const article = document.createElement('article');
  article.className = 'job-card';
  if (beyondLocal) article.classList.add('job-card-beyond');
  const href = applicationUrl(job);
  const id = text(job.posting_id);
  const starred = shortlist.has(id);
  const days = isArchived(job) ? null : daysBetween(job.first_seen, isOpen(job) ? runDay() : (job.removed_date || runDay()));
  const badgeText = isArchived(job) ? 'Archived source' : isOpen(job) ? 'Open' : 'Removed';
  const badgeClass = isArchived(job) ? 'archived' : isOpen(job) ? '' : 'removed';
  const market = marketIdsFor(job).map(marketLabel).join(' + ') || 'Other / not specified';
  const applyMarkup = href
    ? `<a class="apply-link" href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">Apply / view posting <span aria-hidden="true">↗</span></a>`
    : '<span class="apply-link disabled">Application link unavailable</span>';
  article.innerHTML = `
    <div class="job-card-top">
        <span class="job-card-badges"><span class="job-badge ${badgeClass}">${badgeText}${roleMatch(job) ? ' · Finance match' : ''}</span>${beyondLocal ? '<span class="job-badge beyond-market-badge">Beyond local focus</span>' : ''}</span>
      <span class="job-card-actions">
        <span class="job-date">First seen ${escapeHtml(localDate(job.first_seen))}</span>
        <button class="star-button" type="button" data-star-id="${escapeHtml(id)}" aria-pressed="${starred}" aria-label="${starred ? 'Remove from shortlist' : 'Save to shortlist'}" title="${starred ? 'Remove from shortlist' : 'Save to shortlist'}">${starred ? '★' : '☆'}</button>
      </span>
    </div>
    <span class="job-title">${escapeHtml(job.title || 'Untitled role')}</span>
    <span class="job-company">${escapeHtml(job.employer || 'Employer')}</span>
    <div class="job-card-bottom"><span>${escapeHtml(job.location || market)} · ${days == null ? (isArchived(job) ? 'Historical record; source no longer collected' : 'Days open unknown') : `${Math.max(0, days)} days open`}</span>${applyMarkup}</div>`;
  return article;
}

function emptyState(title, message, linkText = 'Browse employer boards', linkHref = './browse.html') {
  const div = document.createElement('div');
  div.className = 'empty-state';
  div.innerHTML = `<strong>${escapeHtml(title)}</strong>${escapeHtml(message)} <a href="${escapeHtml(linkHref)}">${escapeHtml(linkText)} →</a>`;
  return div;
}

function sourceCard(source) {
  const href = safeUrl(source.career_url);
  const card = document.createElement(href ? 'a' : 'div');
  const pending = Boolean(source.status);
  const supplemental = Boolean(source.status_label);
  card.className = `source-card${pending ? ' source-card-pending' : ''}${supplemental ? ' source-card-supplemental' : ''}`;
  if (href) { card.href = href; card.target = '_blank'; card.rel = 'noopener noreferrer'; }
  const label = source.board_name ? `${source.employer} · ${source.board_name}` : source.employer;
  const state = source.status_label
    ? `<span class="source-status source-status-supplemental">${escapeHtml(source.status_label)}</span>`
    : pending ? '<span class="source-status">DISCOVERY</span>' : '';
  card.innerHTML = `<strong>${escapeHtml(label)}</strong><span class="source-card-meta">${state}<span class="source-arrow" aria-hidden="true">↗</span></span>`;
  return card;
}

function renderFooter() {
  const lastRun = document.getElementById('last-updated');
  const footer = document.getElementById('footer-data-state');
  const label = DATA.status.run_time ? `Last run · ${localDateTime(DATA.status.run_time)}` : 'Awaiting first data run';
  if (lastRun) lastRun.textContent = label;
  if (footer) footer.textContent = DATA.status.run_time ? `Last collection: ${localDateTime(DATA.status.run_time)} (your local time)` : 'Waiting for the first successful data run.';
  if (!DATA.status.run_time && !DATA.jobs.length) showNotice('The site is published. Listings will appear after the collector completes its first successful run.');
}

function renderToday() {
  const day = runDay();
  const newIds = Array.isArray(DATA.status.new_today_ids) ? new Set(DATA.status.new_today_ids) : null;
  const fresh = DATA.jobs.filter((job) => newIds
    ? newIds.has(text(job.posting_id)) && isOpen(job)
    : dateOnly(job.first_seen) === day && !truthy(job.first_run) && isOpen(job));
  const removed = DATA.jobs.filter((job) => dateOnly(job.removed_date) === day && !isOpen(job));
  const values = {
    'metric-open': DATA.status.open ?? DATA.jobs.filter(isOpen).length,
    'metric-new': DATA.status.new_today ?? fresh.length,
    'metric-removed': DATA.status.removed_today ?? removed.length,
    'metric-sources': DATA.sources.length,
    'metric-days': DATA.status.days_with_success ?? 0
  };
  for (const [id, value] of Object.entries(values)) {
    const node = document.getElementById(id);
    if (node) node.textContent = String(value);
  }
  const heroSourceCount = document.getElementById('hero-source-count');
  if (heroSourceCount) heroSourceCount.textContent = String(DATA.sources.length);

  for (const [id, jobs, heading] of [
    ['today-new-list', fresh, 'No new postings were first seen in this run.'],
    ['today-removed-list', removed, 'No postings were removed in this run.']
  ]) {
    const list = document.getElementById(id);
    if (!list) continue;
    list.replaceChildren();
    if (!jobs.length) list.append(emptyState('Nothing to report', heading, 'Browse open postings'));
    else jobs.sort((a, b) => text(a.title).localeCompare(text(b.title))).forEach((job) => list.append(jobRow(job)));
  }

  const sourceStatusList = document.getElementById('source-status-list');
  if (sourceStatusList) {
    const results = new Map((DATA.status.sources || []).map((item) => [item.source_id, item]));
    sourceStatusList.replaceChildren();
    DATA.sources.forEach((source) => {
      const result = results.get(source.id);
      const ok = result ? (result.ok ?? result.success) : null;
      const card = document.createElement('article');
      card.className = `source-status-card${ok === false ? ' source-failed' : ok === true ? ' source-succeeded' : ''}`;
      card.innerHTML = `<div class="source-status-head"><strong>${escapeHtml(source.employer)}</strong><span class="run-pill ${ok === false ? 'run-failed' : ok === true ? 'run-ok' : 'run-unknown'}">${ok === true ? 'SUCCESS' : ok === false ? 'FAILED' : 'NO RESULT'}</span></div><p>${ok === null ? 'No source result is recorded for the latest run.' : `${Number(result.count ?? result.postings ?? 0).toLocaleString()} source listings scanned; local matches appear in Browse.`}</p>${ok === false && result.error ? `<small>${escapeHtml(result.error)}</small>` : ''}`;
      sourceStatusList.append(card);
    });
    const succeeded = DATA.sources.filter((source) => {
      const result = results.get(source.id);
      return result && (result.ok ?? result.success);
    }).length;
    const summary = document.getElementById('source-status-summary');
    if (summary) summary.textContent = `${succeeded} of ${DATA.sources.length} boards succeeded · ${DATA.sources.length - succeeded} need attention`;
  }

  const sources = document.getElementById('source-cards');
  if (sources) { sources.replaceChildren(); [...DATA.sources, ...DATA.supplementalSources, ...DATA.candidates].forEach((source) => sources.append(sourceCard(source))); }
}

function readShortlist() {
  try { return new Set(JSON.parse(localStorage.getItem(SHORTLIST_KEY) || '[]')); }
  catch { return new Set(); }
}

function saveShortlist(shortlist) {
  try { localStorage.setItem(SHORTLIST_KEY, JSON.stringify([...shortlist])); }
  catch { showNotice('Your browser could not save the shortlist. Check its storage settings.'); }
}

function renderBrowse() {
  const query = document.getElementById('job-search');
  const market = document.getElementById('market-filter');
  const employer = document.getElementById('employer-filter');
  const location = document.getElementById('location-filter');
  const daysOpen = document.getElementById('days-open-filter');
  const status = document.getElementById('status-filter');
  const sort = document.getElementById('sort-filter');
  const finance = document.getElementById('finance-only');
  const shortlistOnly = document.getElementById('shortlist-only');
  const results = document.getElementById('job-results');
  const count = document.getElementById('result-count');
  const beyondSection = document.getElementById('beyond-region');
  const beyondCountLabel = document.getElementById('beyond-region-count-label');
  const beyondResults = document.getElementById('beyond-region-results');
  const focusButtons = [...document.querySelectorAll('[data-market-choice]')];
  if (!results) return;

  const allJobs = [...DATA.jobs, ...DATA.archiveJobs];
  const employerNames = [...new Set(allJobs.map((job) => text(job.employer)).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  employerNames.forEach((name) => employer.add(new Option(name, name)));
  const params = new URLSearchParams(window.location.search);
  if (['target', 'outside', 'all', 'tulsa_ok', 'northwest_ar'].includes(params.get('market'))) market.value = params.get('market');
  let shortlist = readShortlist();

  const setText = (id, value) => {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  };
  const currentOpen = DATA.jobs.filter(isOpen);
  const localOpen = currentOpen.filter((job) => marketIdsFor(job).length > 0);
  const beyondOpen = currentOpen.filter((job) => marketIdsFor(job).length === 0);
  setText('focus-local-open', localOpen.length.toLocaleString());
  setText('focus-local-finance', localOpen.filter(roleMatch).length.toLocaleString());
  setText('focus-beyond-open', beyondOpen.length.toLocaleString());
  setText('focus-beyond-finance', beyondOpen.filter(roleMatch).length.toLocaleString());

  const updateFocusState = () => {
    focusButtons.forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.marketChoice === market.value));
    });
  };

  const draw = () => {
    let matches = allJobs.slice();
    if (status.value === 'open') matches = matches.filter(isOpen);
    if (status.value === 'removed') matches = matches.filter((job) => !isOpen(job) && !isArchived(job));
    if (status.value === 'archived') matches = matches.filter(isArchived);
    if (employer.value !== 'all') matches = matches.filter((job) => text(job.employer) === employer.value);
    const locationQuery = text(location.value).toLowerCase();
    if (locationQuery) matches = matches.filter((job) => text(job.location).toLowerCase().includes(locationQuery));
    const titleQuery = text(query.value).toLowerCase();
    if (titleQuery) matches = matches.filter((job) => text(job.title).toLowerCase().includes(titleQuery));
    if (finance.checked) matches = matches.filter(roleMatch);
    if (shortlistOnly.checked) matches = matches.filter((job) => shortlist.has(text(job.posting_id)));
    if (daysOpen.value !== 'all') {
      const [min, max] = daysOpen.value === '90+' ? [91, Infinity] : daysOpen.value.split('-').map(Number);
      matches = matches.filter((job) => {
        if (isArchived(job)) return false;
        const duration = daysBetween(job.first_seen, isOpen(job) ? runDay() : (job.removed_date || runDay()));
        return duration !== null && duration >= min && duration <= max;
      });
    }
    const compareByDate = (a, b) => {
      const comparison = dateOnly(a.first_seen).localeCompare(dateOnly(b.first_seen)) || text(a.posting_id).localeCompare(text(b.posting_id));
      return sort.value === 'oldest' ? comparison : -comparison;
    };
    matches.sort(compareByDate);
    let jobs = matches;
    if (market.value === 'target') jobs = matches.filter((job) => marketIdsFor(job).length > 0);
    else if (market.value === 'outside') jobs = matches.filter((job) => marketIdsFor(job).length === 0);
    else if (market.value !== 'all') jobs = matches.filter((job) => marketIdsFor(job).includes(market.value));
    const stateLabel = status.value === 'open' ? 'open' : status.value === 'removed' ? 'removed' : status.value === 'archived' ? 'archived' : 'tracked';
    const marketLabelText = market.value === 'target' ? 'Tulsa + Northwest Arkansas' : market.value === 'outside' ? 'other locations' : market.value === 'tulsa_ok' ? 'Tulsa area' : market.value === 'northwest_ar' ? 'Northwest Arkansas' : 'all locations';
    count.textContent = `${jobs.length.toLocaleString()} ${finance.checked ? 'finance ' : ''}${stateLabel} posting${jobs.length === 1 ? '' : 's'} · ${marketLabelText}`;
    results.replaceChildren();
    if (!jobs.length) {
      results.append(emptyState(allJobs.length ? 'No matching postings found' : 'Job history is not populated yet', allJobs.length ? 'Try changing a filter or clearing the search.' : 'The daily collector will populate the history after its first run.', 'Clear filters', '#clear-filters'));
    } else jobs.forEach((job) => results.append(jobCard(job, shortlist)));

    updateFocusState();
    if (beyondSection && beyondResults) {
      const showBeyondPreview = market.value === 'target';
      beyondSection.hidden = !showBeyondPreview;
      if (showBeyondPreview) {
        const outsideMatches = matches.filter((job) => marketIdsFor(job).length === 0);
        setText('beyond-region-count', outsideMatches.length.toLocaleString());
        if (beyondCountLabel) beyondCountLabel.textContent = `${finance.checked ? 'finance ' : ''}${stateLabel} posting${outsideMatches.length === 1 ? '' : 's'}`;
        const browseButton = document.getElementById('browse-beyond-all');
        if (browseButton) browseButton.innerHTML = `Explore all ${outsideMatches.length.toLocaleString()} broader result${outsideMatches.length === 1 ? '' : 's'} <span aria-hidden="true">↗</span>`;
        beyondResults.replaceChildren();
        if (outsideMatches.length) outsideMatches.slice(0, 3).forEach((job) => beyondResults.append(jobCard(job, shortlist, true)));
        else beyondResults.append(emptyState('No wider-market matches', 'Try clearing a filter to see more openings outside the regional focus.', 'Clear filters', '#clear-filters'));
      }
    }
  };

  const toggleShortlist = (event) => {
    const button = event.target.closest('[data-star-id]');
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    const id = button.dataset.starId;
    if (shortlist.has(id)) shortlist.delete(id); else shortlist.add(id);
    saveShortlist(shortlist);
    draw();
  };
  results.addEventListener('click', toggleShortlist);
  beyondResults?.addEventListener('click', toggleShortlist);
  [query, market, employer, location, daysOpen, status, sort].forEach((input) => input.addEventListener(input === query || input === location ? 'input' : 'change', draw));
  [finance, shortlistOnly].forEach((input) => input.addEventListener('change', draw));
  focusButtons.forEach((button) => button.addEventListener('click', () => {
    market.value = button.dataset.marketChoice;
    draw();
    document.querySelector('.browse-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }));
  document.getElementById('browse-beyond-all')?.addEventListener('click', () => {
    market.value = 'outside';
    draw();
    document.querySelector('.browse-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  document.getElementById('clear-filters')?.addEventListener('click', () => {
    query.value = ''; market.value = 'target'; employer.value = 'all'; location.value = '';
    daysOpen.value = 'all'; status.value = 'open'; sort.value = 'newest'; finance.checked = true; shortlistOnly.checked = false;
    draw(); query.focus();
  });
  draw();

  const links = document.getElementById('browse-source-links');
  if (links) {
    links.replaceChildren();
    [...DATA.sources, ...DATA.supplementalSources, ...DATA.candidates].forEach((source) => {
      const href = safeUrl(source.career_url);
      if (!href) return;
      const a = document.createElement('a'); a.className = 'source-pill'; a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer';
      a.innerHTML = `${escapeHtml(source.employer)} <span aria-hidden="true">↗</span>`;
      links.append(a);
    });
  }
}

function renderMarketCard(id, title, cityDescription, featured = false) {
  const jobs = DATA.jobs.filter((job) => isOpen(job) && roleMatch(job) && marketIdsFor(job).includes(id));
  const byEmployer = new Map();
  jobs.forEach((job) => byEmployer.set(text(job.employer) || 'Other employers', (byEmployer.get(text(job.employer) || 'Other employers') || 0) + 1));
  const top = [...byEmployer.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
  const max = top.length ? top[0][1] : 1;
  const chart = top.length ? top.map(([name, value]) => `<div class="bar-row"><span class="bar-name">${escapeHtml(name)}</span><span class="bar-track"><span class="bar-fill" style="display:block;width:${Math.max(6, value / max * 100)}%"></span></span><span class="bar-number">${value}</span></div>`).join('') : '<div class="chart-empty">No open local finance matches in this history.</div>';
  const sourceCount = DATA.sources.filter((source) => (source.markets || []).includes(id)).length;
  const section = document.createElement('article');
  section.className = `market-card${featured ? ' featured' : ''}`;
  section.innerHTML = `<div class="market-cities" aria-hidden="true">${id === 'tulsa_ok' ? 'TUL' : 'NWA'}</div><div class="market-card-head"><div><p class="eyebrow">${id === 'tulsa_ok' ? 'OKLAHOMA' : 'ARKANSAS'}</p><h2>${escapeHtml(title)}</h2><p class="market-count-label">${escapeHtml(cityDescription)}</p></div><span class="market-index">0${featured ? '1' : '2'}</span></div><div class="market-big-number">${jobs.length}</div><p class="market-count-label">open finance matches</p><div class="market-chart">${chart}</div><div class="market-card-footer"><span>${sourceCount} employer boards</span><a class="text-link${featured ? ' light-link' : ''}" href="./browse.html?market=${id}">Browse market →</a></div>`;
  return section;
}

function chartEmpty(message) { return `<div class="chart-empty">${escapeHtml(message)}</div>`; }

function barChart(rows, className = '') {
  if (!rows.length) return chartEmpty('No observations in the saved history yet.');
  const max = Math.max(1, ...rows.map((row) => Number(row.value) || 0));
  return `<div class="chart-list ${className}">${rows.map((row) => {
    const value = Number(row.value) || 0;
    const width = value ? Math.max(2, value / max * 100) : 0;
    return `<div class="bar-row"><span class="bar-name" title="${escapeHtml(row.name)}">${escapeHtml(row.name)}</span><span class="bar-track"><span class="bar-fill" style="display:block;width:${width}%"></span></span><span class="bar-number">${escapeHtml(value.toLocaleString())}</span></div>`;
  }).join('')}</div>`;
}

function trendChart(rows) {
  if (!rows.length) return chartEmpty('No dates are available in the saved history yet.');
  const max = Math.max(1, ...rows.flatMap((row) => [row.all, row.role]));
  return `<div class="trend-chart">${rows.map((row) => `<div class="trend-row"><span class="bar-name">${escapeHtml(localDate(row.day))}</span><span class="trend-series"><i class="trend-fill trend-all" style="width:${row.all ? Math.max(2, row.all / max * 100) : 0}%"></i><span>All ${row.all}</span></span><span class="trend-series"><i class="trend-fill trend-role" style="width:${row.role ? Math.max(2, row.role / max * 100) : 0}%"></i><span>Role ${row.role}</span></span></div>`).join('')}</div><div class="chart-legend"><span><i class="legend-all"></i>All postings</span><span><i class="legend-role"></i>In-role postings</span></div>`;
}

function reportSection(title, paragraph, chart, id) {
  return `<article class="report-card" id="${id}"><h3>${escapeHtml(title)}</h3><p>${escapeHtml(paragraph)}</p><div class="report-chart">${chart}</div></article>`;
}

function median(values) {
  if (!values.length) return null;
  const sorted = values.slice().sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function dateRange(start, end) {
  const a = dateOnly(start), b = dateOnly(end);
  if (!a || !b || a > b) return [];
  const days = [];
  const cursor = new Date(`${a}T00:00:00Z`);
  const last = new Date(`${b}T00:00:00Z`);
  while (cursor <= last && days.length < 4000) {
    days.push(cursor.toISOString().slice(0, 10));
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return days;
}

function renderHistoryReport() {
  const report = document.getElementById('market-report');
  if (!report) return;
  const validFirstSeen = DATA.jobs.map((job) => dateOnly(job.first_seen)).filter(Boolean).sort();
  const validRemoved = DATA.jobs.map((job) => dateOnly(job.removed_date)).filter(Boolean).sort();
  const start = validFirstSeen[0] || runDay();
  const last = runDay();
  const days = dateRange(start, last);
  const newByDay = new Map(days.map((day) => [day, { all: 0, role: 0 }]));
  const removedByDay = new Map(days.map((day) => [day, 0]));
  DATA.jobs.forEach((job) => {
    const first = dateOnly(job.first_seen);
    if (!truthy(job.first_run) && newByDay.has(first)) {
      newByDay.get(first).all += 1;
      if (roleMatch(job)) newByDay.get(first).role += 1;
    }
    const removed = dateOnly(job.removed_date);
    if (removedByDay.has(removed)) removedByDay.set(removed, removedByDay.get(removed) + 1);
  });
  const newRows = [...newByDay.entries()].map(([day, values]) => ({ day, ...values }));
  const newTotal = newRows.reduce((sum, row) => sum + row.all, 0);
  const recentActivity = newRows.slice(-7).reduce((sum, row) => sum + row.all, 0);
  const removedRows = [...removedByDay.entries()].map(([day, value]) => ({ name: localDate(day), value })).filter((row) => row.value > 0);
  const removedTotal = removedRows.reduce((sum, row) => sum + row.value, 0);

  const openJobs = DATA.jobs.filter(isOpen);
  const openByEmployer = new Map();
  openJobs.forEach((job) => {
    const name = text(job.employer) || 'Employer not specified';
    openByEmployer.set(name, (openByEmployer.get(name) || 0) + 1);
  });
  const employerRows = [...openByEmployer.entries()].map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value || a.name.localeCompare(b.name)).slice(0, 15);

  const lifetimes = DATA.jobs.filter((job) => !truthy(job.first_run) && dateOnly(job.removed_date) && dateOnly(job.first_seen))
    .map((job) => daysBetween(job.first_seen, job.removed_date)).filter((value) => value !== null && value >= 0);
  const lifetimeMedian = median(lifetimes);
  const lifetimeBuckets = [
    { name: '0–7 days', min: 0, max: 7 },
    { name: '8–14 days', min: 8, max: 14 },
    { name: '15–30 days', min: 15, max: 30 },
    { name: '31+ days', min: 31, max: Infinity }
  ].map((bucket) => ({ name: bucket.name, value: lifetimes.filter((value) => value >= bucket.min && value <= bucket.max).length }));

  const matured = DATA.jobs.filter((job) => !truthy(job.first_run) && dateOnly(job.first_seen) && daysBetween(job.first_seen, last) >= 7);
  const removedWithinSeven = matured.filter((job) => {
    const duration = dateOnly(job.removed_date) ? daysBetween(job.first_seen, job.removed_date) : null;
    return duration !== null && duration >= 0 && duration <= 7;
  }).length;
  const earlyShare = matured.length ? removedWithinSeven / matured.length : 0;
  const shareRows = [
    { name: 'Removed within 7 days', value: removedWithinSeven },
    { name: 'Not removed within 7 days', value: matured.length - removedWithinSeven }
  ];

  const locations = new Map();
  openJobs.forEach((job) => {
    const parts = text(job.location).split(';').map((part) => part.trim()).filter(Boolean);
    (parts.length ? [...new Set(parts)] : ['Location not specified']).forEach((part) => locations.set(part, (locations.get(part) || 0) + 1));
  });
  const locationRows = [...locations.entries()].map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value || a.name.localeCompare(b.name)).slice(0, 15);

  const reportDate = document.getElementById('report-date-range');
  if (reportDate) reportDate.textContent = `${localDate(start)} – ${localDate(last)} · ${DATA.jobs.length.toLocaleString()} history rows`;
  report.innerHTML = [
    reportSection(
      `${newTotal.toLocaleString()} new postings were first seen in the history`,
      `Daily counts exclude first-run baseline postings. The chart compares all postings with the selected finance-title rule; ${recentActivity.toLocaleString()} postings were first seen in the latest seven calendar days.`,
      trendChart(newRows), 'report-new'
    ),
    reportSection(
      `${removedTotal.toLocaleString()} postings were removed from tracked boards`,
      'A posting is counted on the UTC date when its source returned a successful snapshot without that posting. Failed source requests do not mark jobs removed.',
      barChart(removedRows), 'report-removed'
    ),
    reportSection(
      `${employerRows.length ? employerRows[0].name : 'No employer'} has the most open postings`,
      `Open counts are grouped by employer as of the latest saved run (${localDate(last)}). The chart shows the 15 employers with the most open history rows.`,
      barChart(employerRows), 'report-employers'
    ),
    reportSection(
      lifetimeMedian === null ? 'There are no completed posting lifetimes yet' : `Median posting lifetime: ${Number.isInteger(lifetimeMedian) ? lifetimeMedian : lifetimeMedian.toFixed(1)} days`,
      'Lifetime is the removed UTC date minus the first-seen UTC date. First-run postings are omitted because their true start dates are unknown.',
      barChart(lifetimeBuckets), 'report-lifetime'
    ),
    reportSection(
      matured.length ? `${(earlyShare * 100).toFixed(1)}% of matured postings were removed within seven days` : 'Seven-day removal share is not available yet',
      `${removedWithinSeven} of ${matured.length} non-first-run postings were first seen at least seven days before the latest run; the numerator counts postings removed no more than seven days after first seen.`,
      barChart(shareRows), 'report-seven-day'
    ),
    reportSection(
      `${locationRows.length ? locationRows[0].name : 'No location'} is the most common open-posting location`,
      'Locations are counted from open history rows as of the latest run. Multi-location postings contribute once to each listed location.',
      barChart(locationRows), 'report-locations'
    )
  ].join('');
}

function renderMarket() {
  const grid = document.getElementById('market-grid');
  if (grid) {
    grid.replaceChildren();
    grid.append(renderMarketCard('tulsa_ok', 'Tulsa area', 'Tulsa · Broken Arrow · Tahlequah · Bartlesville', true));
    grid.append(renderMarketCard('northwest_ar', 'Northwest Arkansas', 'Bentonville · Fayetteville · Springdale'));
  }
  renderHistoryReport();
  const sources = document.getElementById('market-source-list');
  if (sources) {
    sources.replaceChildren();
    [...DATA.sources, ...DATA.supplementalSources].forEach((source) => {
      const href = safeUrl(source.career_url);
      const card = document.createElement(href ? 'a' : 'div'); card.className = 'market-source';
      if (href) { card.href = href; card.target = '_blank'; card.rel = 'noopener noreferrer'; }
      const names = `${(source.markets || []).map(marketLabel).join(' + ')}${source.status_label ? ' · supplemental link' : ''}`;
      card.innerHTML = `<strong>${escapeHtml(source.employer)}</strong><span>${escapeHtml(names)}</span>`;
      sources.append(card);
    });
  }
  const count = document.getElementById('market-source-count');
  if (count) count.textContent = `${DATA.sources.length} active boards · ${DATA.supplementalSources.length} supplemental links · ${DATA.candidates.length} to validate`;
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
