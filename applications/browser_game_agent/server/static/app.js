/* Browser Game Agent - Frontend Logic */

(function () {
  'use strict';

  // ---- State ----
  let sessionId = null;
  let ws = null;
  let iframeFocused = false;
  let isReprogress = false;

  // ---- DOM refs ----
  const phaseInput = document.getElementById('phase-input');
  const phaseProgress = document.getElementById('phase-progress');
  const phaseDone = document.getElementById('phase-done');
  const phaseReprogress = document.getElementById('phase-reprogress');

  const iframeContainer = document.getElementById('iframe-container');
  const gameFrame = document.getElementById('game-frame');
  const gamePlaceholder = document.getElementById('game-placeholder');
  const focusOverlay = document.getElementById('focus-overlay');
  const testBar = document.getElementById('test-bar');
  const uiBadge = document.getElementById('ui-test-badge');
  const funcBadge = document.getElementById('func-test-badge');
  const btnViewCode = document.getElementById('btn-view-code');
  const btnOpenNew = document.getElementById('btn-open-new');
  const btnReload = document.getElementById('btn-reload');

  const taskInput = document.getElementById('task-input');
  const btnGenerate = document.getElementById('btn-generate');
  const logBox = document.getElementById('log-box');
  const rlogBox = document.getElementById('rlog-box');

  const doneInfo = document.getElementById('done-info');
  const btnModification = document.getElementById('btn-modification');
  const btnAsking = document.getElementById('btn-asking');
  const subModification = document.getElementById('sub-modification');
  const subAsking = document.getElementById('sub-asking');
  const modificationInput = document.getElementById('modification-input');
  const btnSubmitModification = document.getElementById('btn-submit-modification');
  const askingInput = document.getElementById('asking-input');
  const btnSubmitAsk = document.getElementById('btn-submit-ask');
  const answerBox = document.getElementById('answer-box');

  // API settings
  const inputApiKey = document.getElementById('input-api-key');
  const inputBaseUrl = document.getElementById('input-base-url');
  const inputModel = document.getElementById('input-model');
  const apiSettingsToggle = document.getElementById('api-settings-toggle');
  const apiSettingsBody = document.getElementById('api-settings-body');
  const toggleArrow = document.getElementById('toggle-arrow');

  // Code modal
  const codeModalBackdrop = document.getElementById('code-modal-backdrop');
  const codeModalClose = document.getElementById('code-modal-close');
  const codeFileTree = document.getElementById('code-file-tree');
  const codeFileHeader = document.getElementById('code-file-header');
  const codeContent = document.getElementById('code-content');

  // ---- API Settings ----
  apiSettingsToggle.addEventListener('click', () => {
    const hidden = apiSettingsBody.classList.toggle('hidden');
    toggleArrow.textContent = hidden ? '▶' : '▼';
  });

  function loadApiSettings() {
    inputApiKey.value = localStorage.getItem('bga_api_key') || '';
    inputBaseUrl.value = localStorage.getItem('bga_base_url') || '';
    inputModel.value = localStorage.getItem('bga_model') || '';
    // Auto-expand if no key set yet
    if (!inputApiKey.value) {
      apiSettingsBody.classList.remove('hidden');
      toggleArrow.textContent = '▼';
    }
  }

  function saveApiSettings() {
    localStorage.setItem('bga_api_key', inputApiKey.value.trim());
    localStorage.setItem('bga_base_url', inputBaseUrl.value.trim());
    localStorage.setItem('bga_model', inputModel.value.trim());
  }

  function getApiParams() {
    const api_key = inputApiKey.value.trim() || '';
    const base_url = inputBaseUrl.value.trim() || '';
    const model = inputModel.value.trim() || '';
    return { api_key, base_url, model };
  }

  loadApiSettings();
  [inputApiKey, inputBaseUrl, inputModel].forEach(el => el.addEventListener('change', saveApiSettings));

  // ---- Default game suggestions ----
  const DEFAULT_SUGGESTIONS = [
    'A snake game where the player collects food to grow longer. The snake speeds up over time. Classic controls with arrow keys.',
    'A breakout/arkanoid game with colorful bricks, a paddle, and a bouncing ball. Each row of bricks has a different color and point value.',
    'A simple platformer where the player jumps between platforms to reach the top. Avoid falling into the void. Use arrow keys or WASD.',
    'A top-down space shooter. The player controls a spaceship and shoots waves of approaching aliens. Collect power-ups for faster fire rate.',
    'A 2048-style sliding tile puzzle. Merge tiles with the same number to reach 2048. Smooth animations and score tracking.',
    'A Flappy Bird clone. Tap or press Space to flap and fly through gaps between pipes. Display a high score.',
    'A memory card matching game with 16 cards (8 pairs). Flip two cards at a time; match all pairs to win. Track moves and time.',
    'A Tetris game with all 7 tetrominoes, line-clear scoring, and increasing speed. Next-piece preview panel on the side.',
  ];
  let suggestionIndex = 0;

  function fillSuggestion() {
    taskInput.value = DEFAULT_SUGGESTIONS[suggestionIndex];
    suggestionIndex = (suggestionIndex + 1) % DEFAULT_SUGGESTIONS.length;
    taskInput.focus();
    taskInput.selectionStart = taskInput.selectionEnd = taskInput.value.length;
  }

  const btnSuggestion = document.getElementById('btn-suggestion');
  if (btnSuggestion) btnSuggestion.addEventListener('click', fillSuggestion);

  // Tab key shortcut when textarea is focused and empty
  taskInput.addEventListener('keydown', (e) => {
    if (e.key === 'Tab' && taskInput.value.trim() === '') {
      e.preventDefault();
      fillSuggestion();
    }
  });

  // ---- Step helpers ----
  const STEP_IDS = {
    planning: 'step-planning',
    coding: 'step-coding',
    readme: 'step-readme',
    testing: 'step-testing',
    testing_round_1: 'step-testing',
    testing_round_2: 'step-testing',
    testing_round_3: 'step-testing',
    fixing: 'step-fixing',
    fixing_round_1: 'step-fixing',
    fixing_round_2: 'step-fixing',
    fixing_round_3: 'step-fixing',
    deploy: 'step-deploy',
    done: 'step-deploy',
  };
  const RSTEP_IDS = {
    modifying: 'rstep-modifying',
    planning: 'rstep-modifying',
    coding: 'rstep-modifying',
    testing: 'rstep-testing',
    testing_round_1: 'rstep-testing',
    testing_round_2: 'rstep-testing',
    testing_round_3: 'rstep-testing',
    fixing: 'rstep-fixing',
    fixing_round_1: 'rstep-fixing',
    fixing_round_2: 'rstep-fixing',
    fixing_round_3: 'rstep-fixing',
    done: 'rstep-done',
    readme: 'rstep-done',
    deploy: 'rstep-done',
  };
  // Original step labels to restore when step goes idle
  const STEP_LABELS = {};
  let activeStep = null;

  function setStep(stepId, status, labelOverride) {
    const el = document.getElementById(stepId);
    if (!el) return;
    el.classList.remove('active', 'done');
    if (status === 'active') el.classList.add('active');
    if (status === 'done') el.classList.add('done');
    const statusSpan = el.querySelector('.step-status');
    if (statusSpan) statusSpan.textContent = status === 'active' ? '⟳ Running' : status === 'done' ? '✓ Done' : '—';
    const labelSpan = el.querySelector('.step-label');
    if (labelSpan) {
      // Save original label once
      if (!STEP_LABELS[stepId]) STEP_LABELS[stepId] = labelSpan.textContent;
      if (labelOverride) {
        labelSpan.textContent = labelOverride;
      } else if (status !== 'active') {
        // Restore original label when no longer active
        labelSpan.textContent = STEP_LABELS[stepId];
      }
    }
  }

  function activateStep(stage) {
    // Determine round label for testing/fixing stages
    let labelOverride = null;
    const roundMatch = stage.match(/^(testing|fixing)_round_(\d+)$/);
    if (roundMatch) {
      const kind = roundMatch[1] === 'testing' ? 'Testing' : 'Fixing';
      const n = roundMatch[2];
      labelOverride = `${kind} (${n}/3)`;
    }

    // In reprogress mode, prefer modification step IDs
    let stepId;
    if (isReprogress) {
      stepId = RSTEP_IDS[stage] || STEP_IDS[stage];
    } else {
      stepId = STEP_IDS[stage] || RSTEP_IDS[stage];
    }
    if (!stepId) return;

    if (activeStep && activeStep !== stepId) setStep(activeStep, 'done');
    activeStep = stepId;
    setStep(stepId, 'active', labelOverride);
  }

  // ---- Log helpers ----
  function appendLog(box, stage, message) {
    if (!box) return;
    const p = document.createElement('p');
    p.className = `log-entry stage-${stage}`;
    const ts = new Date().toLocaleTimeString('en-US', { hour12: false });
    p.textContent = `[${ts}] [${stage}] ${message}`;
    box.appendChild(p);
    box.scrollTop = box.scrollHeight;
  }

  // ---- Show/hide phases ----
  function showPhase(name) {
    phaseInput.classList.add('hidden');
    phaseProgress.classList.add('hidden');
    phaseDone.classList.add('hidden');
    phaseReprogress.classList.add('hidden');
    if (name === 'input') phaseInput.classList.remove('hidden');
    if (name === 'progress') phaseProgress.classList.remove('hidden');
    if (name === 'done') phaseDone.classList.remove('hidden');
    if (name === 'reprogress') {
      phaseDone.classList.remove('hidden');
      phaseReprogress.classList.remove('hidden');
      subModification.classList.add('hidden');
      subAsking.classList.add('hidden');
    }
  }

  // ---- WebSocket ----
  function connectWS(sid, logTarget, onDone) {
    if (ws) ws.close();
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/${sid}`);

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === 'ping') return;
      if (msg.type === 'progress') {
        appendLog(logTarget, msg.stage, msg.message);
        activateStep(msg.stage);
      } else if (msg.type === 'done') {
        activateStep('done');
        if (onDone) onDone(msg);
      } else if (msg.type === 'error') {
        appendLog(logTarget, 'error', msg.message || 'Unknown error');
      }
    };

    ws.onerror = () => appendLog(logTarget, 'error', 'WebSocket error');
    ws.onclose = () => {
      if (ws._expectingDone) pollStatus(sid, onDone);
    };
    ws._expectingDone = true;
  }

  async function pollStatus(sid, onDone) {
    for (let i = 0; i < 120; i++) {
      await delay(3000);
      try {
        const r = await fetch(`/api/status/${sid}`);
        const data = await r.json();
        if (data.status === 'done' || data.status === 'error') {
          if (onDone) onDone(data);
          return;
        }
      } catch (_) {}
    }
  }

  function delay(ms) { return new Promise(r => setTimeout(r, ms)); }

  // ---- iframe focus handling ----
  // Prevent arrow keys and space from scrolling the outer page
  window.addEventListener('keydown', (e) => {
    if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Space', ' '].includes(e.key) && iframeFocused) {
      e.preventDefault();
    }
  }, { passive: false });

  gameFrame.addEventListener('load', () => {
    if (gameFrame.src && gameFrame.src !== 'about:blank') {
      iframeFocused = false;
      focusOverlay.classList.remove('hidden');
    }
  });

  focusOverlay.addEventListener('click', () => {
    iframeFocused = true;
    focusOverlay.classList.add('hidden');
    gameFrame.focus();
    try {
      gameFrame.contentWindow.focus();
      gameFrame.contentDocument.body.click();
    } catch (_) {}
  });

  // ---- Load game into iframe ----
  function loadGame(gameUrl) {
    gamePlaceholder.classList.add('hidden');
    iframeContainer.classList.remove('hidden');
    gameFrame.src = gameUrl;
    testBar.classList.remove('hidden');
    iframeFocused = false;
    focusOverlay.classList.remove('hidden');
  }

  function updateBadges(uiPassed, funcPassed) {
    uiBadge.textContent = `UI: ${uiPassed === true ? '✓ Pass' : uiPassed === false ? '✗ Fail' : '—'}`;
    uiBadge.className = `badge ${uiPassed === true ? 'pass' : uiPassed === false ? 'fail' : ''}`;
    funcBadge.textContent = `Logic: ${funcPassed === true ? '✓ Pass' : funcPassed === false ? '✗ Fail' : '—'}`;
    funcBadge.className = `badge ${funcPassed === true ? 'pass' : funcPassed === false ? 'fail' : ''}`;
  }

  // ---- Generate ----
  btnGenerate.addEventListener('click', async () => {
    const task = taskInput.value.trim();
    if (!task) { taskInput.focus(); return; }

    const { api_key, base_url, model } = getApiParams();

    saveApiSettings();
    btnGenerate.disabled = true;
    btnGenerate.textContent = 'Starting...';
    logBox.innerHTML = '';
    activeStep = null;
    isReprogress = false;
    [...new Set(Object.values(STEP_IDS))].forEach(id => setStep(id, 'idle'));
    showPhase('progress');

    try {
      const res = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task, api_key, base_url, model }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      sessionId = data.session_id;

      connectWS(sessionId, logBox, async (doneMsg) => {
        ws._expectingDone = false;
        if (doneMsg.status === 'error' && !doneMsg.game_url) {
          // Hard pipeline error with no output — show retry
          const errMsg = doneMsg.error || doneMsg.message || 'Generation failed';
          appendLog(logBox, 'error', errMsg);
          showRetryButton();
          return;
        }
        // Use game_url from message, or fall back to status API
        let gameUrl = doneMsg.game_url;
        if (!gameUrl) {
          try {
            const s = await fetch(`/api/status/${sessionId}`).then(r => r.json());
            gameUrl = s.game_url;
          } catch (_) {}
        }
        if (gameUrl) {
          loadGame(gameUrl);
          updateBadges(doneMsg.ui_test_passed, doneMsg.functional_test_passed);
          showDonePanel(task, doneMsg);
        } else {
          // Game URL not available — still show done panel without iframe
          updateBadges(doneMsg.ui_test_passed, doneMsg.functional_test_passed);
          showDonePanel(task, doneMsg);
        }
      });
    } catch (e) {
      appendLog(logBox, 'error', e.message);
      showPhase('input');
      btnGenerate.disabled = false;
      btnGenerate.textContent = 'Generate Game';
    }
  });

  function showRetryButton() {
    btnGenerate.disabled = false;
    btnGenerate.textContent = 'Generate Game';
    // Add a "← Back" button if not already present
    if (!document.getElementById('btn-back-to-input')) {
      const btn = document.createElement('button');
      btn.id = 'btn-back-to-input';
      btn.className = 'btn-secondary';
      btn.textContent = '← Try Again';
      btn.addEventListener('click', () => {
        btn.remove();
        showPhase('input');
      });
      logBox.parentNode.insertBefore(btn, logBox.nextSibling);
    }
  }

  // ---- Safe string conversion (handles objects) ----
  function safeStr(v) {
    if (v == null) return '';
    if (typeof v === 'string') return v;
    return JSON.stringify(v, null, 2);
  }

  function escapeHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // Parse a flat report string into structured line items.
  // Detects sentences/fragments ending with PASS or FAIL, or items starting with [XX-N] PASS/FAIL.
  function parseReportLines(reportStr) {
    if (!reportStr) return null;
    const raw = reportStr.replace(/\r\n/g, '\n').replace(/\r/g, '\n');

    // Strategy 1: Split by bracket-prefixed items like [UI-1], [F-2], [Checkpoint 1]
    const bracketPattern = /\[[\w\s\-]+\d*\]\s*/g;
    const hasBrackets = bracketPattern.test(raw);

    let chunks;
    if (hasBrackets) {
      // Split before each [XX...] marker
      chunks = raw.split(/(?=\[[\w\s\-]+\d*\])/).map(s => s.trim()).filter(Boolean);
    } else {
      // Fallback: split on ". " followed by capital letter or newlines
      chunks = raw.split(/(?<=\.)\s+(?=[A-Z\[])|(?<=\n)(?=[A-Z\-\d\[])/g)
        .map(s => s.trim()).filter(Boolean);
    }

    const items = chunks.map(chunk => {
      const upper = chunk.toUpperCase();
      // Check for PASS/FAIL anywhere meaningful in the chunk
      const passMatch = /\bPASS\b/i.test(chunk);
      const failMatch = /\bFAIL\b/i.test(chunk);

      if (passMatch && !failMatch) {
        // Remove the PASS keyword and clean up separators like " - ", ": "
        const text = chunk.replace(/\s*[-:]\s*PASS\b\.?\s*/i, ' ')
                         .replace(/\bPASS\b\s*[-:]?\s*/i, '')
                         .replace(/\s+/g, ' ').trim();
        return { status: 'pass', text };
      } else if (failMatch) {
        const text = chunk.replace(/\s*[-:]\s*FAIL\b\.?\s*/i, ' ')
                         .replace(/\bFAIL\b\s*[-:]?\s*/i, '')
                         .replace(/\s+/g, ' ').trim();
        return { status: 'fail', text };
      }
      return { status: 'info', text: chunk.trim() };
    });

    const hasVerdict = items.some(i => i.status === 'pass' || i.status === 'fail');
    return hasVerdict ? items : null;
  }

  function renderReportItems(items) {
    return items.map((item, idx) => {
      const num = `<span class="report-num">${idx + 1}.</span>`;
      if (item.status === 'pass') {
        return `<div class="report-item report-pass">${num}<span class="report-badge pass">PASS</span><span class="report-text">${escapeHtml(item.text)}</span></div>`;
      } else if (item.status === 'fail') {
        return `<div class="report-item report-fail">${num}<span class="report-badge fail">FAIL</span><span class="report-text">${escapeHtml(item.text)}</span></div>`;
      }
      return `<div class="report-item report-info">${num}<span class="report-text">${escapeHtml(item.text)}</span></div>`;
    }).join('');
  }

  function buildProgressBar(items) {
    const passed = items.filter(i => i.status === 'pass').length;
    const failed = items.filter(i => i.status === 'fail').length;
    const total = passed + failed;
    if (total === 0) return '';
    const pct = Math.round((passed / total) * 100);
    const cls = pct >= 70 ? 'good' : 'bad';
    return `<div class="test-progress-bar"><span class="bar-label">${passed}/${total} passed</span><div class="bar-track"><div class="bar-fill ${cls}" style="width:${pct}%"></div></div></div>`;
  }

  function buildTestSummaryHtml(uiPassed, funcPassed, uiReport, funcReport) {
    const uiColor = uiPassed === true ? 'var(--success)' : uiPassed === false ? 'var(--error)' : 'var(--text-muted)';
    const funcColor = funcPassed === true ? 'var(--success)' : funcPassed === false ? 'var(--error)' : 'var(--text-muted)';
    const uiLabel = uiPassed === true ? '✓ Passed' : uiPassed === false ? '✗ Failed' : '—';
    const funcLabel = funcPassed === true ? '✓ Passed' : funcPassed === false ? '✗ Failed' : '—';
    let html = `
      <div class="summary-tests">
        <span class="summary-test-item" style="color:${uiColor}">UI Test: ${uiLabel}</span>
        <span class="summary-test-sep">|</span>
        <span class="summary-test-item" style="color:${funcColor}">Logic Test: ${funcLabel}</span>
      </div>`;

    const uiReportStr = safeStr(uiReport);
    const funcReportStr = safeStr(funcReport);

    if (uiReportStr) {
      const openAttr = uiPassed === false ? ' open' : '';
      const parsed = parseReportLines(uiReportStr);
      const progressBar = parsed ? buildProgressBar(parsed) : '';
      const body = parsed
        ? `${progressBar}<div class="report-list">${renderReportItems(parsed)}</div>`
        : `<pre class="report-plain">${escapeHtml(uiReportStr)}</pre>`;
      html += `<details class="summary-report"${openAttr}><summary>UI Test Report</summary>${body}</details>`;
    }
    if (funcReportStr) {
      const openAttr = funcPassed === false ? ' open' : '';
      const parsed = parseReportLines(funcReportStr);
      const progressBar = parsed ? buildProgressBar(parsed) : '';
      const body = parsed
        ? `${progressBar}<div class="report-list">${renderReportItems(parsed)}</div>`
        : `<pre class="report-plain">${escapeHtml(funcReportStr)}</pre>`;
      html += `<details class="summary-report"${openAttr}><summary>Logic Test Report</summary>${body}</details>`;
    }
    return html;
  }

  function showDonePanel(task, doneMsg) {
    const taskSnippet = task.length > 80 ? task.slice(0, 80) + '…' : task;
    doneInfo.innerHTML = `
      <div class="summary-header">
        <span class="summary-icon">✅</span>
        <div class="summary-body">
          <strong>Game generated!</strong>
          <span class="summary-task">"${escapeHtml(taskSnippet)}"</span>
        </div>
      </div>
      ${buildTestSummaryHtml(doneMsg.ui_test_passed, doneMsg.functional_test_passed, doneMsg.ui_test_report, doneMsg.functional_test_report)}
    `;
    showPhase('done');
    switchActionTab('modification');
  }

  // ---- Action tabs ----
  function switchActionTab(tab) {
    btnModification.classList.toggle('active', tab === 'modification');
    btnAsking.classList.toggle('active', tab === 'asking');
    subModification.classList.toggle('hidden', tab !== 'modification');
    subAsking.classList.toggle('hidden', tab !== 'asking');
    answerBox.classList.add('hidden');
    answerBox.textContent = '';
  }

  btnModification.addEventListener('click', () => switchActionTab('modification'));
  btnAsking.addEventListener('click', () => switchActionTab('asking'));

  // ---- Modification submit ----
  btnSubmitModification.addEventListener('click', async () => {
    const req = modificationInput.value.trim();
    if (!req || !sessionId) return;

    btnSubmitModification.disabled = true;
    rlogBox.innerHTML = '';
    isReprogress = true;
    activeStep = null;
    [...new Set(Object.values(RSTEP_IDS))].forEach(id => setStep(id, 'idle'));
    const reprogStepsEl = document.getElementById('reprogress-steps');
    if (reprogStepsEl) reprogStepsEl.classList.remove('hidden');
    showPhase('reprogress');

    try {
      const res = await fetch(`/api/modify/${sessionId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ modification_request: req }),
      });
      if (!res.ok) throw new Error(await res.text());

      connectWS(sessionId, rlogBox, (doneMsg) => {
        ws._expectingDone = false;
        isReprogress = false;
        // Keep rlogBox visible but show the done state — don't hide reprogress completely
        // Replace progress steps with a collapsible log summary
        const reprogSteps = document.getElementById('reprogress-steps');
        if (reprogSteps) reprogSteps.classList.add('hidden');
        subModification.classList.remove('hidden');
        subAsking.classList.add('hidden');
        btnSubmitModification.disabled = false;
        if (doneMsg.game_url) {
          loadGame(doneMsg.game_url + '?t=' + Date.now());
          updateBadges(doneMsg.ui_test_passed, doneMsg.functional_test_passed);
          const reqSnippet = req.length > 60 ? req.slice(0, 60) + '…' : req;
          doneInfo.innerHTML = `
            <div class="summary-header">
              <span class="summary-icon">✏️</span>
              <div class="summary-body">
                <strong>Modification applied!</strong>
                <span class="summary-task">"${escapeHtml(reqSnippet)}"</span>
              </div>
            </div>
            ${buildTestSummaryHtml(doneMsg.ui_test_passed, doneMsg.functional_test_passed, doneMsg.ui_test_report, doneMsg.functional_test_report)}
          `;
        } else {
          const errMsg = doneMsg.error || doneMsg.message || 'Modification failed';
          doneInfo.innerHTML = `
            <div class="summary-header">
              <span class="summary-icon">❌</span>
              <div class="summary-body">
                <strong>Modification failed</strong>
                <span class="summary-task" style="color:var(--text-muted);font-size:0.8rem">${escapeHtml(safeStr(errMsg))}</span>
              </div>
            </div>
            <p style="font-size:0.8rem;color:var(--text-muted);margin-top:0.5rem">Check the log above for details. The previous game version is still active.</p>
          `;
        }
      });
    } catch (e) {
      appendLog(rlogBox, 'error', e.message);
      isReprogress = false;
      const reprogSteps2 = document.getElementById('reprogress-steps');
      if (reprogSteps2) reprogSteps2.classList.add('hidden');
      subModification.classList.remove('hidden');
      btnSubmitModification.disabled = false;
    }
  });

  // ---- Ask submit ----
  btnSubmitAsk.addEventListener('click', async () => {
    const question = askingInput.value.trim();
    if (!question || !sessionId) return;

    btnSubmitAsk.disabled = true;
    answerBox.textContent = '⟳ Asking the agent...';
    answerBox.classList.remove('hidden');

    try {
      const res = await fetch(`/api/ask/${sessionId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      });
      if (!res.ok) throw new Error(await res.text());

      for (let i = 0; i < 60; i++) {
        await delay(2000);
        const s = await fetch(`/api/status/${sessionId}`).then(r => r.json());
        if (s.status === 'done' && s.explanation) {
          answerBox.textContent = s.explanation;
          break;
        } else if (s.status === 'error') {
          answerBox.textContent = '❌ Error: ' + (s.error || 'Unknown error');
          break;
        }
      }
    } catch (e) {
      answerBox.textContent = '❌ ' + e.message;
    } finally {
      btnSubmitAsk.disabled = false;
    }
  });

  // ---- Open/Reload buttons ----
  btnOpenNew.addEventListener('click', () => {
    const src = gameFrame.src && gameFrame.src !== 'about:blank' ? gameFrame.src.split('?')[0] : null;
    if (src) window.open(src, '_blank');
    else if (sessionId) window.open(`/games/${sessionId}/index.html`, '_blank');
  });
  btnReload.addEventListener('click', () => {
    if (gameFrame.src) {
      const url = gameFrame.src.split('?')[0];
      gameFrame.src = url + '?t=' + Date.now();
      iframeFocused = false;
      focusOverlay.classList.remove('hidden');
    }
  });

  // ---- Code Viewer ----
  btnViewCode.addEventListener('click', async () => {
    if (!sessionId) return;
    openCodeModal();
    await Promise.all([loadCodeFiles(sessionId), loadBuildLog(sessionId)]);
  });

  async function loadBuildLog(sid) {
    const logPanel = document.getElementById('code-log-content');
    if (!logPanel) return;
    try {
      const res = await fetch(`/api/log/${sid}`);
      if (!res.ok) throw new Error('No log');
      const data = await res.json();
      if (data.logs && data.logs.length > 0) {
        logPanel.innerHTML = data.logs.map(entry => {
          const colorMap = {
            planning: '#60a5fa', coding: '#a78bfa', readme: '#94a3b8',
            testing: '#fbbf24', fixing: '#fb923c', deploy: '#22c55e',
            done: '#22c55e', error: '#f87171', modifying: '#a78bfa',
            asking: '#60a5fa',
          };
          const color = colorMap[entry.stage] || 'var(--text-muted)';
          return `<p style="color:${color}">[${entry.ts}] [${entry.stage}] ${escapeHtml(entry.message)}</p>`;
        }).join('');
      } else {
        logPanel.innerHTML = '<span style="color:var(--text-muted)">No build log available.</span>';
      }
    } catch (_) {
      logPanel.innerHTML = '<span style="color:var(--text-muted)">No build log available.</span>';
    }
  }

  function openCodeModal() {
    codeModalBackdrop.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    codeFileTree.innerHTML = '<div class="tree-loading">Loading files...</div>';
    codeFileHeader.textContent = 'Select a file';
    codeContent.textContent = '—';

    // Reset sidebar to files tab
    const tabFiles = document.getElementById('tab-files');
    const tabLog = document.getElementById('tab-log');
    const codeLogPanel = document.getElementById('code-log-panel');
    if (tabFiles && tabLog && codeLogPanel) {
      tabFiles.classList.add('active');
      tabLog.classList.remove('active');
      codeFileTree.classList.remove('hidden');
      codeLogPanel.classList.add('hidden');
    }
  }

  function closeCodeModal() {
    codeModalBackdrop.classList.add('hidden');
    document.body.style.overflow = '';
  }

  // Sidebar tab switching
  const tabFilesBtn = document.getElementById('tab-files');
  const tabLogBtn = document.getElementById('tab-log');
  if (tabFilesBtn) {
    tabFilesBtn.addEventListener('click', () => {
      tabFilesBtn.classList.add('active');
      tabLogBtn.classList.remove('active');
      codeFileTree.classList.remove('hidden');
      document.getElementById('code-log-panel').classList.add('hidden');
    });
  }
  if (tabLogBtn) {
    tabLogBtn.addEventListener('click', () => {
      tabLogBtn.classList.add('active');
      tabFilesBtn.classList.remove('active');
      codeFileTree.classList.add('hidden');
      document.getElementById('code-log-panel').classList.remove('hidden');
    });
  }

  codeModalClose.addEventListener('click', closeCodeModal);
  codeModalBackdrop.addEventListener('click', (e) => {
    if (e.target === codeModalBackdrop) closeCodeModal();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !codeModalBackdrop.classList.contains('hidden')) closeCodeModal();
  });

  async function loadCodeFiles(sid) {
    try {
      const res = await fetch(`/api/code/${sid}`);
      if (!res.ok) throw new Error('Failed to load files');
      const data = await res.json();
      // Sort: index.html first, README.md second, then alphabetical
      data.files.sort((a, b) => {
        if (a.name === 'index.html') return -1;
        if (b.name === 'index.html') return 1;
        if (a.name === 'README.md') return -1;
        if (b.name === 'README.md') return 1;
        return a.name.localeCompare(b.name);
      });
      renderFileTree(data.files);
      const mainFile = data.files.find(f => f.name === 'index.html') || data.files[0];
      if (mainFile) showFileContent(mainFile);
    } catch (e) {
      codeFileTree.innerHTML = `<div class="tree-error">Error: ${e.message}</div>`;
    }
  }

  function renderFileTree(files) {
    codeFileTree.innerHTML = '';
    if (!files.length) {
      codeFileTree.innerHTML = '<div class="tree-loading">No files found</div>';
      return;
    }
    files.forEach(file => {
      const item = document.createElement('div');
      item.className = 'tree-item';
      const icon = getFileIcon(file.name);
      const sizeStr = formatBytes(file.size);
      item.innerHTML = `<span class="tree-icon">${icon}</span><span class="tree-name">${file.name}</span><span class="tree-size">${sizeStr}</span>`;
      item.addEventListener('click', () => {
        document.querySelectorAll('.tree-item').forEach(el => el.classList.remove('active'));
        item.classList.add('active');
        showFileContent(file);
      });
      codeFileTree.appendChild(item);
    });
  }

  function showFileContent(file) {
    codeFileHeader.textContent = file.name;
    const escaped = file.content
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
    codeContent.innerHTML = escaped;
    if (window.hljs) {
      codeContent.className = getLangClass(file.name);
      hljs.highlightElement(codeContent);
    }
    document.querySelectorAll('.tree-item').forEach(el => {
      const name = el.querySelector('.tree-name');
      if (name && name.textContent === file.name) el.classList.add('active');
      else el.classList.remove('active');
    });
  }

  function getFileIcon(name) {
    if (name.endsWith('.html')) return '🌐';
    if (name.endsWith('.css')) return '🎨';
    if (name.endsWith('.js')) return '⚡';
    if (name.endsWith('.md')) return '📝';
    if (name.endsWith('.json')) return '{}';
    return '📄';
  }

  function getLangClass(name) {
    if (name.endsWith('.html')) return 'language-html';
    if (name.endsWith('.css')) return 'language-css';
    if (name.endsWith('.js')) return 'language-javascript';
    if (name.endsWith('.md')) return 'language-markdown';
    if (name.endsWith('.json')) return 'language-json';
    return 'language-plaintext';
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    return `${(bytes / 1024).toFixed(1)} KB`;
  }

})();
