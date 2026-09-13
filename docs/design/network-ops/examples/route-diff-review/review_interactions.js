// UI-only interactions for the synthetic review. No log parsing or device access.
let navigationItems = [];
let navigationIndex = -1;
let returnTarget = null;

function refreshNavigation() {
  navigationItems = Array.from(document.querySelectorAll('[data-mode-panel] .route-group')).filter(g =>
    !g.parentElement.hidden && !g.hidden && !['UNKNOWN', 'UNCHANGED'].includes(g.dataset.change));
  navigationIndex = -1;
  document.querySelectorAll('.selected-difference').forEach(g => g.classList.remove('selected-difference'));
  renderNavigation();
}

function renderNavigation() {
  $('difference-position').textContent = (navigationIndex < 0 ? '未選択' : navigationIndex + 1) + ' / ' + navigationItems.length + ' 件';
  $('previous-difference').disabled = navigationIndex <= 0;
  $('next-difference').disabled = navigationIndex >= navigationItems.length - 1;
}

function selectDifference(index) {
  if (index < 0 || index >= navigationItems.length) return;
  document.querySelectorAll('.selected-difference').forEach(g => g.classList.remove('selected-difference'));
  navigationIndex = index;
  const target = navigationItems[index];
  target.classList.add('selected-difference');
  target.focus({preventScroll: true});
  target.scrollIntoView({block: 'start'});
  renderNavigation();
}

$('previous-difference').addEventListener('click', () => selectDifference(navigationIndex - 1));
$('next-difference').addEventListener('click', () => selectDifference(navigationIndex + 1));

document.querySelectorAll('[data-summary-filter]').forEach(button => button.addEventListener('click', () => {
  const selection = JSON.parse(button.dataset.summaryFilter);
  $('host').value = selection.host;
  $('vrf').value = selection.vrf;
  $('af').value = selection.family;
  $('mode').value = selection.mode;
  $('change-type').value = selection.change_type;
  $('reason').value = '';
  $('query').value = '';
  $('show-unchanged').checked = false;
  document.querySelector('[data-tab="compare"]').click();
  update();
  selectDifference(0);
}));

document.querySelectorAll('[data-coverage-jump]').forEach(button => button.addEventListener('click', () => {
  const target = $('coverage-detail');
  target.focus({preventScroll: true});
  target.scrollIntoView({block: 'start'});
}));

document.querySelectorAll('[data-log-jump]').forEach(button => button.addEventListener('click', () => {
  const jump = JSON.parse(button.dataset.logJump);
  returnTarget = button.closest('.route-group');
  const index = navigationItems.indexOf(returnTarget);
  if (index >= 0) selectDifference(index);
  document.querySelector('[data-tab="raw"]').click();
  $('raw-host').value = jump.host;
  $('raw-mode').value = jump.mode;
  $('raw-color').value = 'semantic';
  $('raw-query').value = '';
  // Proportional scrolling must not undo the two independent evidence positions.
  $('raw-sync').checked = false;
  updateRaw();
  document.querySelectorAll('.jump-target').forEach(line => line.classList.remove('jump-target'));
  const section = Array.from(document.querySelectorAll('.raw-host')).find(s => s.dataset.rawHost === jump.host);
  for (const side of ['before', 'after']) {
    const pane = section.querySelector('.raw-scroll[data-side="' + side + '"]');
    const evidence = jump[side];
    const lines = Array.from(pane.querySelectorAll('.raw-line')).filter(line =>
      Number(line.dataset.line) >= evidence.start && Number(line.dataset.line) <= evidence.end);
    lines.forEach(line => line.classList.add('jump-target'));
    if (lines.length) pane.scrollTop += lines[0].getBoundingClientRect().top - pane.getBoundingClientRect().top - 40;
  }
  const describe = side => side + ' L' + jump[side].start + '–' + jump[side].end +
    (jump[side].present ? '' : '（この経路が存在しないため、確認対象の VRF section を表示）');
  $('raw-jump-message').textContent = jump.host + ' / ' + jump.prefix + ': ' + describe('before') + ' / ' + describe('after') +
    '。両側の証跡を強調しています。比例スクロール同期は OFF にしました。';
  $('raw-jump-context').hidden = false;
  $('raw-jump-context').scrollIntoView({block: 'start'});
}));

$('return-to-diff').addEventListener('click', () => {
  document.querySelector('[data-tab="compare"]').click();
  if (returnTarget && !returnTarget.hidden) {
    returnTarget.focus({preventScroll: true});
    returnTarget.scrollIntoView({block: 'start'});
  }
});

$('raw-host').addEventListener('input', () => {
  $('raw-jump-context').hidden = true;
  document.querySelectorAll('.jump-target').forEach(line => line.classList.remove('jump-target'));
});

refreshNavigation();
