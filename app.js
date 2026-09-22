const state = {
  catalog: [],
  pool: [],
  sequence: [],
  audioSequence: [],
  settings: null,
  index: -1,
  answered: false,
  timer: null,
  countdownTimer: null,
  turnDeadline: null,
  turnStartedAt: 0,
  gameActive: false,
  correct: 0,
  incorrect: 0,
  missed: 0,
  targetMatches: 0,
  voices: [],
  audioCache: new Map(),
  audioUnlocked: false,
  audioUnlockPromise: null,
  preparedSignature: null,
  preparedSequence: null,
  preparedAudioSequence: null,
  preparing: false,
};

const HISTORY_STORAGE_KEY = "english-phrase-n-back-history";

const $ = (selector) => document.querySelector(selector);
const elements = {
  setupScreen: $("#setup-screen"),
  gameScreen: $("#game-screen"),
  resultsScreen: $("#results-screen"),
  setupForm: $("#setup-form"),
  audioBadge: $("#audio-badge"),
  themeToggle: $("#theme-toggle"),
  startGame: $("#start-game"),
  setupError: $("#setup-error"),
  nBack: $("#n-back"),
  rounds: $("#rounds"),
  audioLanguage: $("#audio-language"),
  displayLanguage: $("#display-language"),
  voiceEnglish: $("#voice-english"),
  voiceSpanish: $("#voice-spanish"),
  testVoiceEnglish: $("#test-voice-english"),
  testVoiceSpanish: $("#test-voice-spanish"),
  interval: $("#interval"),
  intervalValue: $("#interval-value"),
  feedbackSound: $("#feedback-sound"),
  catalogCount: $("#catalog-count"),
  voiceStatus: $("#voice-status"),
  subtitleSelect: $("#subtitle-select"),
  processSubtitles: $("#process-subtitles"),
  deleteSubtitles: $("#delete-subtitles"),
  subtitleProcessing: $("#subtitle-processing"),
  subtitleStatus: $("#subtitle-status"),
  subtitleCount: $("#subtitle-count"),
  subtitleBar: $("#subtitle-bar"),
  audioPreparation: $("#audio-preparation"),
  preparationStatus: $("#preparation-status"),
  preparationCount: $("#preparation-count"),
  preparationBar: $("#preparation-bar"),
  quitGame: $("#quit-game"),
  roundLabel: $("#round-label"),
  scoreLabel: $("#score-label"),
  progressBar: $("#progress-bar"),
  turnCounter: $("#turn-counter"),
  countdown: $("#countdown"),
  warmupNote: $("#warmup-note"),
  phraseText: $("#phrase-text"),
  phraseTranslation: $("#phrase-translation"),
  feedback: $("#feedback"),
  answerNo: $("#answer-no"),
  answerYes: $("#answer-yes"),
  repeatGame: $("#repeat-game"),
  backToSetup: $("#back-to-setup"),
  resultsSummary: $("#results-summary"),
  historySessions: $("#history-sessions"),
  historyRounds: $("#history-rounds"),
  historyAccuracy: $("#history-accuracy"),
  historyBest: $("#history-best"),
  historyList: $("#history-list"),
  clearHistory: $("#clear-history"),
  accuracyScore: $("#accuracy-score"),
  correctCount: $("#correct-count"),
  incorrectCount: $("#incorrect-count"),
  missedCount: $("#missed-count"),
  successAudio: $("#success-audio"),
  errorAudio: $("#error-audio"),
};

const filteredPool = () => state.catalog;

const randomItem = (items) => items[Math.floor(Math.random() * items.length)];

const normalizePhraseText = (text) => text.trim().toLocaleLowerCase();

function setTheme(theme, persist = true) {
  const activeTheme = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = activeTheme;
  const nextTheme = activeTheme === "dark" ? "claro" : "oscuro";
  elements.themeToggle.setAttribute("aria-label", `Cambiar a tema ${nextTheme}`);
  elements.themeToggle.title = `Cambiar a tema ${nextTheme}`;
  document.querySelector('meta[name="theme-color"]')?.setAttribute(
    "content",
    activeTheme === "dark" ? "#111827" : "#f3f5fc",
  );
  if (persist) {
    try {
      localStorage.setItem("english-phrase-n-back-theme", activeTheme);
    } catch {
      // El tema sigue funcionando aunque el navegador bloquee el almacenamiento.
    }
  }
}

try {
  setTheme(localStorage.getItem("english-phrase-n-back-theme") || "dark", false);
} catch {
  setTheme("dark", false);
}

const samePhraseContent = (left, right) => Boolean(
  left && right && left.id === right.id
);

const shuffle = (items) => {
  const shuffled = [...items];
  for (let index = shuffled.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    [shuffled[index], shuffled[swapIndex]] = [shuffled[swapIndex], shuffled[index]];
  }
  return shuffled;
};

const chooseDifferent = (items, excludedId) => {
  const available = items.filter((item) => item.id !== excludedId);
  return randomItem(available.length ? available : items);
};

const chooseDistractor = (items, excludedIds, excludedPhrases) => {
  const available = items.filter((item) => (
    !excludedIds.has(item.id)
    && !excludedPhrases.some((excluded) => samePhraseContent(item, excluded))
  ));
  console.log(`Choosing distractor from ${available.length} available phrases (excluded ${excludedIds.size} IDs)`);
  return randomItem(available.length ? available : items);
};

function createSequence(pool, nBack, scoredRounds) {
  const visualSequence = [];
  const audioSequence = [];
  const totalTurns = scoredRounds + nBack;

  // Create an array with exactly half matches and half non-matches for scored rounds
  const matchPattern = [];
  const halfMatches = Math.floor(scoredRounds / 2);
  for (let i = 0; i < halfMatches; i++) matchPattern.push(true);
  for (let i = 0; i < scoredRounds - halfMatches; i++) matchPattern.push(false);

  // Shuffle the pattern to randomize match/non-match order
  for (let i = matchPattern.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [matchPattern[i], matchPattern[j]] = [matchPattern[j], matchPattern[i]];
  }

  let matchIndex = 0;
  let cursor = 0;

  // Create visual sequence
  for (let i = 0; i < totalTurns; i++) {
    let phrase = null;
    for (let attempt = 0; attempt < pool.length; attempt++) {
      const candidate = pool[(cursor + attempt) % pool.length];
      if (!samePhraseContent(candidate, visualSequence[i - 1] || null)) {
        phrase = candidate;
        cursor = (cursor + attempt + 1) % pool.length;
        break;
      }
    }
    phrase ||= chooseDifferent(pool, visualSequence[i - 1]?.id);
    visualSequence.push(phrase);
  }

  // Create audio sequence
  for (let i = 0; i < totalTurns; i++) {
    if (i < nBack) {
      audioSequence.push(null); // Warmup: no audio
    } else {
      const shouldMatch = matchPattern[matchIndex++];
      const targetPhrase = visualSequence[i - nBack]; // The phrase from n turns ago

      if (shouldMatch) {
        audioSequence.push(targetPhrase); // Audio IS the phrase from n turns ago
      } else {
        // Audio is NOT the phrase from n turns ago (distractor)
        const availablePhrases = pool.filter(p => p.id !== targetPhrase.id);
        if (availablePhrases.length > 0) {
          const randomIndex = Math.floor(Math.random() * availablePhrases.length);
          audioSequence.push(availablePhrases[randomIndex]);
        } else {
          audioSequence.push(pool[0]);
        }
      }
    }
  }

  return { visualSequence, audioSequence };
}

function showScreen(screen) {
  [elements.setupScreen, elements.gameScreen, elements.resultsScreen].forEach((item) => {
    item.hidden = item !== screen;
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function updateIntervalLabel() {
  const seconds = Number(elements.interval.value) / 1000;
  elements.intervalValue.textContent = `${seconds.toFixed(1).replace(".", ",")} s`;
}

function languageLabel(language) {
  return language === "en" ? "inglés" : "español";
}

function updateAudioBadge() {
  const english = elements.audioLanguage.value === "en";
  elements.audioBadge.textContent = english ? "EN · AUDIO" : "ES · AUDIO";
  elements.audioBadge.setAttribute("aria-label", `Audio en ${languageLabel(elements.audioLanguage.value)}`);
}

async function checkTtsServer() {
  if (state.catalog.length) {
    const localField = elements.audioLanguage.value === "en" ? "audioEnglish" : "audioSpanish";
    const localLabel = elements.audioLanguage.value === "en" ? "ingleses" : "españoles";
    const localCount = state.catalog.filter((phrase) => phrase[localField]).length;
    if (localCount === state.catalog.length) {
      elements.voiceStatus.textContent = `Audios ${localLabel} pregrabados · ${localCount}/${state.catalog.length} disponibles`;
      return true;
    }
  }
  try {
    const response = await fetch(`/api/tts/health?language=${encodeURIComponent(elements.audioLanguage.value)}`);
    if (!response.ok) throw new Error("TTS server unavailable");
    const health = await response.json();
    elements.voiceStatus.textContent = `Cache de audio disponible · ${health.voiceName}`;
    return true;
  } catch {
    elements.voiceStatus.textContent = "Inicia server.py antes de jugar.";
    return false;
  }
}

async function loadVoiceOptions(language, select) {
  const response = await fetch(`/api/voices?language=${encodeURIComponent(language)}`);
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !Array.isArray(result.voices) || !result.voices.length) {
    throw new Error(`No hay voces disponibles para ${language}.`);
  }

  const previous = select.value;
  select.replaceChildren();
  const groups = new Map();
  result.voices.forEach((voice) => {
    const option = document.createElement("option");
    option.value = voice.id;
    option.textContent = voice.name;
    const engineLabel = voice.engine === "mms-tts" ? "MMS-TTS (Transformers)" : "macOS say";
    if (!groups.has(engineLabel)) {
      const group = document.createElement("optgroup");
      group.label = engineLabel;
      groups.set(engineLabel, group);
      select.append(group);
    }
    groups.get(engineLabel).append(option);
  });
  if (result.voices.some((voice) => voice.id === previous)) {
    select.value = previous;
  }
}

async function loadAllVoiceOptions() {
  await Promise.all([
    loadVoiceOptions("en", elements.voiceEnglish),
    loadVoiceOptions("es", elements.voiceSpanish),
  ]);
  elements.voiceStatus.textContent = "Selecciona las voces y procesa los subtítulos para generar los audios.";
}

async function preloadAudio(audio) {
  if (audio.readyState >= 3) return audio;
  await new Promise((resolve, reject) => {
    audio.addEventListener("canplaythrough", resolve, { once: true });
    audio.addEventListener("error", () => reject(new Error("No se pudo cargar un audio preparado.")), { once: true });
    audio.load();
  });
  return audio;
}

async function loadAudioFile(url) {
  try {
    const response = await fetch(url, { method: "HEAD", cache: "no-store" });
    if (!response.ok) {
      return null;
    }
    const audio = new Audio(url);
    audio.preload = "auto";
    await new Promise((resolve, reject) => {
      audio.addEventListener("canplaythrough", resolve, { once: true });
      audio.addEventListener("error", () => reject(new Error(`Failed to load audio: ${url}`)), { once: true });
      audio.addEventListener("stalled", () => reject(new Error(`Audio stalled: ${url}`)), { once: true });
      audio.load();
      setTimeout(() => reject(new Error(`Audio load timeout: ${url}`)), 5000);
    });
    return audio;
  } catch (error) {
    return null;
  }
}

async function requestAudio(text, language, phrase = null) {
  if (state.gameActive) {
    throw new Error("No se puede generar audio mientras la partida está activa.");
  }

  const localPath = language === "en" ? phrase?.audioEnglish : phrase?.audioSpanish;
  if (localPath) {
    const localAudio = await loadAudioFile(localPath);
    if (localAudio) {
      console.log(`Using local audio: ${localPath}`);
      return localAudio;
    }
  }

  console.log(`Checking cached audio for: ${text.substring(0, 30)}...`);
  const response = await fetch("/api/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, language }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || "No se pudo generar el audio.");
  const audio = new Audio(result.url);
  audio.preload = "auto";
  await new Promise((resolve, reject) => {
    if (audio.readyState >= 3) {
      resolve();
      return;
    }
    audio.addEventListener("canplaythrough", resolve, { once: true });
    audio.addEventListener("error", () => reject(new Error("No se pudo cargar el audio generado.")), { once: true });
    audio.load();
  });
  return audio;
}

function unlockAudioPlayback() {
  if (state.audioUnlocked) return Promise.resolve();
  if (state.audioUnlockPromise) return state.audioUnlockPromise;
  const audio = [...state.audioCache.values()].find(Boolean);
  if (!audio) return Promise.resolve();

  // Browsers may block playback started after an async preparation step. Start
  // one muted frame directly from the start button's user gesture to unlock
  // subsequent prepared audio elements.
  audio.muted = true;
  const unlockPromise = audio.play();
  const restore = () => {
    audio.pause();
    audio.currentTime = 0;
    audio.muted = false;
    state.audioUnlocked = true;
  };
  if (unlockPromise) {
    state.audioUnlockPromise = unlockPromise.then(restore).catch(() => {
      audio.muted = false;
    });
  } else {
    restore();
    state.audioUnlockPromise = Promise.resolve();
  }
  return state.audioUnlockPromise;
}

function playPreparedAudio(audio) {
  if (!audio) return Promise.resolve();
  audio.pause();
  audio.currentTime = 0;
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      resolve();
    };
    const fail = () => {
      if (settled) return;
      settled = true;
      reject(new Error("El navegador no pudo reproducir el audio de la frase."));
    };
    audio.addEventListener("ended", finish, { once: true });
    audio.addEventListener("error", fail, { once: true });
    const playPromise = audio.play();
    if (playPromise) playPromise.catch(fail);
    setTimeout(finish, 30000);
  });
}

function pausePreparedAudio() {
  state.audioCache.forEach((audio) => {
    audio.pause();
    audio.currentTime = 0;
  });
}

function playFeedback(kind) {
  if (!elements.feedbackSound.checked) return;
  const audio = kind === "success" ? elements.successAudio : elements.errorAudio;
  audio.pause();
  audio.currentTime = 0;
  audio.play().catch(() => {
    elements.voiceStatus.textContent = "Activa el audio del navegador para oír el feedback.";
  });
}

function setAnswerButtons(enabled) {
  elements.answerNo.disabled = !enabled;
  elements.answerYes.disabled = !enabled;
}

function isWarmup() {
  return state.index < state.settings.nBack;
}

function updateGameProgress() {
  const scoredProgress = Math.max(0, state.index - state.settings.nBack + 1);
  const percentage = Math.min(100, (scoredProgress / state.settings.rounds) * 100);
  elements.progressBar.style.width = `${percentage}%`;
  elements.scoreLabel.textContent = `${state.correct} aciertos`;
  elements.turnCounter.textContent = String(Math.max(1, scoredProgress)).padStart(2, "0");
  if (isWarmup()) {
    elements.roundLabel.textContent = `Calentamiento ${state.index + 1}/${state.settings.nBack}`;
  } else {
    elements.roundLabel.textContent = `Ronda ${scoredProgress}/${state.settings.rounds}`;
  }
}

function renderTurn() {
  const current = state.sequence[state.index];
  state.answered = false;
  const displayInEnglish = state.settings.displayLanguage === "en";
  elements.phraseText.textContent = displayInEnglish ? current.en : current.es;
  elements.phraseTranslation.textContent = displayInEnglish ? current.es : current.en;
  elements.feedback.textContent = "";
  elements.feedback.className = "feedback";
  elements.feedback.removeAttribute("aria-label");
  elements.warmupNote.textContent = isWarmup()
    ? "Escucha y observa. Las respuestas empiezan después del calentamiento."
    : `Responde Sí si el audio corresponde a la frase de hace ${state.settings.nBack} turnos.`;
  setAnswerButtons(!isWarmup());
  updateGameProgress();
}

function updateCountdown() {
  if (!state.gameActive) return;
  if (!state.turnDeadline) {
    elements.countdown.textContent = "Escucha…";
    return;
  }
  const remaining = Math.max(0, state.turnDeadline - performance.now());
  elements.countdown.textContent = `${(remaining / 1000).toFixed(1).replace(".", ",")} s`;
}

function clearTurnTimers() {
  window.clearTimeout(state.timer);
  window.clearInterval(state.countdownTimer);
  state.timer = null;
  state.countdownTimer = null;
  state.turnDeadline = null;
}

function beginTurn() {
  if (!state.gameActive) return;
  renderTurn();
  const turnIndex = state.index;
  const audioPhrase = state.audioSequence[turnIndex];
  state.turnStartedAt = performance.now();
  state.turnDeadline = null;
  updateCountdown();
  window.clearInterval(state.countdownTimer);
  state.countdownTimer = window.setInterval(updateCountdown, 100);

  const audioReady = audioPhrase ? playPreparedAudio(state.audioCache.get(audioPhrase.id)) : Promise.resolve();
  audioReady.then(() => {
    if (!state.gameActive || state.index !== turnIndex) return;
    const elapsed = performance.now() - state.turnStartedAt;
    const remaining = Math.max(250, state.settings.intervalMs - elapsed);
    state.turnDeadline = performance.now() + remaining;
    updateCountdown();
    state.timer = window.setTimeout(finishTurn, remaining);
  }).catch((error) => {
    if (!state.gameActive || state.index !== turnIndex) return;
    state.gameActive = false;
    clearTurnTimers();
    pausePreparedAudio();
    setAnswerButtons(false);
    elements.feedback.textContent = "Audio no disponible";
    elements.feedback.className = "feedback incorrect";
    elements.setupError.hidden = false;
    elements.setupError.textContent = `${error.message} Comprueba el volumen y los permisos de audio del navegador.`;
    showScreen(elements.setupScreen);
  });
}

function finishTurn() {
  if (!isWarmup() && !state.answered) {
    state.missed += 1;
    state.incorrect += 1;
    elements.feedback.textContent = "✕";
    elements.feedback.setAttribute("aria-label", "Respuesta incorrecta: tiempo agotado");
    elements.feedback.className = "feedback incorrect";
    playFeedback("error");
  }
  state.index += 1;
  if (state.index >= state.sequence.length) {
    finishGame();
    return;
  }
  state.timer = window.setTimeout(beginTurn, 220);
}

function registerAnswer(answer) {
  if (isWarmup() || state.answered) return;
  state.answered = true;

  const audioPhrase = state.audioSequence[state.index];
  const targetPhrase = state.sequence[state.index - state.settings.nBack]; // Phrase from n turns ago

  // N-Back logic: Does the audio match the phrase from n turns ago?
  const matches = audioPhrase && targetPhrase && audioPhrase.id === targetPhrase.id;
  const correct = answer === matches;

  if (matches) state.targetMatches += 1;
  if (correct) state.correct += 1;
  else state.incorrect += 1;

  elements.feedback.textContent = correct ? "✓" : "✕";
  elements.feedback.setAttribute("aria-label", correct ? "Respuesta correcta" : "Respuesta incorrecta");
  elements.feedback.className = `feedback ${correct ? "correct" : "incorrect"}`;
  setAnswerButtons(false);
  playFeedback(correct ? "success" : "error");
  updateGameProgress();
}

async function preloadSequenceAudios() {
  const missingAudio = [...new Set(
    state.audioSequence
      .filter(Boolean)
      .filter((phrase) => !state.audioCache.get(phrase.id))
      .map((phrase) => phrase.id),
  )];
  if (missingAudio.length) {
    throw new Error("Faltan audios preparados para esta sesión. Vuelve a preparar la partida.");
  }

  const sessionAudios = [...new Set(
    state.audioSequence
      .filter(Boolean)
      .map((phrase) => state.audioCache.get(phrase.id))
  )];
  await Promise.all(sessionAudios.map((audio) => preloadAudio(audio)));
}

async function releaseServerModels() {
  const response = await fetch("/api/models/cleanup", { method: "POST" });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(result.error || "No se pudieron liberar los modelos de IA.");
  }
}

async function startGame(settings) {
  const signature = settingsSignature(settings);
  if (
    state.preparedSignature !== signature
    || !state.preparedSequence
    || !state.preparedAudioSequence
  ) {
    throw new Error("La sesión todavía no está preparada. Pulsa «Preparar sesión».");
  }

  // The sequence was prepared together with its audios. Do not generate a new
  // sequence here: doing so could reference phrases whose audio was not loaded.
  state.settings = settings;
  state.sequence = state.preparedSequence;
  state.audioSequence = state.preparedAudioSequence;
  state.index = 0;
  state.correct = 0;
  state.incorrect = 0;
  state.missed = 0;
  state.targetMatches = 0;
  const audioUnlock = unlockAudioPlayback();
  await preloadSequenceAudios();
  await audioUnlock;
  await releaseServerModels();
  // Consume this prepared sequence. Returning to setup or starting another
  // game must prepare a fresh randomized order while reusing cached audio.
  state.preparedSignature = null;
  state.gameActive = true;
  clearTurnTimers();
  showScreen(elements.gameScreen);
  beginTurn();
}

function finishGame() {
  state.gameActive = false;
  clearTurnTimers();
  pausePreparedAudio();
  setAnswerButtons(false);
  const scored = state.settings.rounds;
  const accuracy = Math.round((state.correct / scored) * 100);
  elements.accuracyScore.textContent = `${accuracy}%`;
  elements.correctCount.textContent = state.correct;
  elements.incorrectCount.textContent = Math.max(0, state.incorrect - state.missed);
  elements.missedCount.textContent = state.missed;
  elements.resultsSummary.textContent = `${state.correct} respuestas correctas de ${scored}. Has detectado ${state.targetMatches} audios n-back reales.`;
  recordSession();
  showScreen(elements.resultsScreen);
}

function getSettings() {
  return {
    nBack: Number(elements.nBack.value),
    rounds: Number(elements.rounds.value),
    intervalMs: Number(elements.interval.value),
    audioLanguage: elements.audioLanguage.value,
    displayLanguage: elements.displayLanguage.value,
  };
}

function settingsSignature(settings) {
  return JSON.stringify(settings);
}

function readHistory() {
  try {
    const saved = JSON.parse(localStorage.getItem(HISTORY_STORAGE_KEY) || "[]");
    return Array.isArray(saved) ? saved : [];
  } catch {
    return [];
  }
}

function formatHistoryDate(timestamp) {
  return new Intl.DateTimeFormat("es-ES", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(timestamp));
}

function renderHistoricalStats() {
  const history = readHistory();
  const totalRounds = history.reduce((sum, session) => sum + session.rounds, 0);
  const averageAccuracy = history.length
    ? Math.round(history.reduce((sum, session) => sum + session.accuracy, 0) / history.length)
    : 0;
  const bestAccuracy = history.length ? Math.max(...history.map((session) => session.accuracy)) : 0;
  elements.historySessions.textContent = history.length;
  elements.historyRounds.textContent = totalRounds;
  elements.historyAccuracy.textContent = `${averageAccuracy}%`;
  elements.historyBest.textContent = `${bestAccuracy}%`;
  elements.historyList.replaceChildren();

  if (!history.length) {
    const empty = document.createElement("p");
    empty.className = "history-empty";
    empty.textContent = "Tus resultados aparecerán aquí al terminar la primera partida.";
    elements.historyList.append(empty);
    return;
  }

  history.slice(0, 5).forEach((session) => {
    const item = document.createElement("div");
    item.className = "history-item";
    const details = document.createElement("div");
    details.className = "history-item-details";
    const title = document.createElement("strong");
    title.textContent = `${session.nBack}-back · ${session.accuracy}%`;
    const subtitle = document.createElement("span");
    subtitle.textContent = `${session.correct}/${session.rounds} aciertos · ${formatHistoryDate(session.timestamp)}`;
    details.append(title, subtitle);
    const language = document.createElement("span");
    language.className = "history-language";
    language.textContent = session.audioLanguage === "en" ? "Audio EN" : "Audio ES";
    item.append(details, language);
    elements.historyList.append(item);
  });
}

function recordSession() {
  const scored = state.settings.rounds;
  const session = {
    timestamp: new Date().toISOString(),
    nBack: state.settings.nBack,
    rounds: scored,
    intervalMs: state.settings.intervalMs,
    audioLanguage: state.settings.audioLanguage,
    displayLanguage: state.settings.displayLanguage,
    correct: state.correct,
    incorrect: Math.max(0, state.incorrect - state.missed),
    missed: state.missed,
    accuracy: Math.round((state.correct / scored) * 100),
    targetMatches: state.targetMatches,
  };
  const history = [session, ...readHistory()].slice(0, 50);
  try {
    localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(history));
  } catch {
    // El juego sigue funcionando si el almacenamiento del navegador no está disponible.
  }
  renderHistoricalStats();
}

function setSetupControlsDisabled(disabled) {
  elements.setupForm.querySelectorAll("select, input").forEach((control) => {
    control.disabled = disabled;
  });
  elements.testVoiceEnglish.disabled = disabled;
  elements.testVoiceSpanish.disabled = disabled;
}

function resetPreparedSession() {
  if (state.preparing) return;
  state.preparedSignature = null;
  state.preparedSequence = null;
  state.preparedAudioSequence = null;
  state.audioUnlocked = false;
  state.audioUnlockPromise = null;
  state.audioCache = new Map();
  elements.startGame.textContent = "Preparar sesión →";
  elements.audioPreparation.hidden = true;
  updateCatalogLabel();
}

async function prepareSession(settings) {
  if (state.preparing) return;
  // Randomize catalog order for every new game preparation. Audio remains
  // attached to each phrase object and is retrieved by phrase ID below.
  const pool = shuffle(filteredPool());
  const generated = createSequence(pool, settings.nBack, settings.rounds);
  const sequence = [...generated.visualSequence, ...generated.audioSequence.filter(Boolean)];
  const phrasesInSequence = sequence.filter((phrase, idx, self) =>
    self.findIndex((p) => p.id === phrase.id) === idx,
  );

  state.preparing = true;
  elements.startGame.disabled = true;
  setSetupControlsDisabled(true);
  state.settings = settings;
  state.pool = pool;
  state.sequence = generated.visualSequence;
  state.audioSequence = generated.audioSequence;
  state.preparedSequence = null;
  state.preparedAudioSequence = null;
  state.audioCache = new Map();
  elements.audioPreparation.hidden = false;
  elements.preparationStatus.textContent = "Comprobando audios preparados…";
  elements.preparationCount.textContent = `0/${phrasesInSequence.length}`;
  elements.preparationBar.style.width = "0%";

  // Check and cache local audio in one pass while reporting progress.
  const phrasesNeedingAudio = [];

  for (const [index, phrase] of phrasesInSequence.entries()) {
    const hasLocalAudio = settings.audioLanguage === "en"
      ? phrase.audioEnglish
      : phrase.audioSpanish;

    if (hasLocalAudio) {
      const localPath = settings.audioLanguage === "en" ? phrase.audioEnglish : phrase.audioSpanish;
      const localAudio = await loadAudioFile(localPath);
      if (localAudio) {
        state.audioCache.set(phrase.id, localAudio);
      } else {
        phrasesNeedingAudio.push(phrase);
      }
    } else {
      phrasesNeedingAudio.push(phrase);
    }

    const completed = index + 1;
    elements.preparationCount.textContent = `${completed}/${phrasesInSequence.length}`;
    elements.preparationBar.style.width = `${(completed / phrasesInSequence.length) * 100}%`;
    elements.preparationStatus.textContent = `Comprobando audio ${completed} de ${phrasesInSequence.length}…`;
  }

  const phrasesToPrepare = [...new Map(phrasesNeedingAudio.map((phrase) => [phrase.id, phrase])).values()];
  const preparationTasks = settings.audioLanguage === "es"
    ? [...new Map(phrasesToPrepare.map((phrase) => [
      normalizePhraseText(phrase.es),
      { text: phrase.es, phrase, rows: [] },
    ])).values()]
    : phrasesToPrepare.map((phrase) => ({
      text: phrase.en,
      phrase,
      rows: [],
    }));

  if (settings.audioLanguage === "es") {
    const taskByText = new Map(
      preparationTasks.map((task) => [normalizePhraseText(task.text), task]),
    );
    phrasesToPrepare.forEach((phrase) => {
      const task = taskByText.get(normalizePhraseText(phrase.es));
      task.rows.push(phrase);
    });
  } else {
    preparationTasks.forEach((task) => task.rows.push(task.phrase));
  }

  if (preparationTasks.length === 0) {
    try {
      // All audio already available locally
      elements.preparationStatus.textContent = "Usando audios pregrabados…";
      elements.preparationCount.textContent = `${phrasesInSequence.length}/${phrasesInSequence.length}`;
      elements.preparationBar.style.width = "100%";
      await preloadSequenceAudios();
      state.preparedSequence = generated.visualSequence;
      state.preparedAudioSequence = generated.audioSequence;
      state.preparedSignature = settingsSignature(settings);
      elements.preparationStatus.textContent = "Audio listo para la partida.";
      elements.startGame.textContent = "Empezar partida →";
      elements.setupError.hidden = true;
    } catch (error) {
      state.preparedSignature = null;
      state.preparedSequence = null;
      state.preparedAudioSequence = null;
      elements.setupError.hidden = false;
      elements.setupError.textContent = error.message;
      elements.audioPreparation.hidden = true;
    } finally {
      state.preparing = false;
      setSetupControlsDisabled(false);
      elements.startGame.disabled = false;
    }
    return;
  }

  elements.preparationStatus.textContent = settings.audioLanguage === "en"
    ? "Comprobando audios ingleses pregrabados…"
    : `Preparando ${preparationTasks.length} audios nuevos…`;
  elements.preparationCount.textContent = `0/${preparationTasks.length}`;
  elements.preparationBar.style.width = "0%";
  try {
    if (!(await checkTtsServer())) throw new Error("El motor de voz natural no está disponible.");
    let nextIndex = 0;
    let completed = 0;
    const worker = async () => {
      while (nextIndex < preparationTasks.length) {
        const index = nextIndex;
        nextIndex += 1;
        const task = preparationTasks[index];
        const audio = await requestAudio(task.text, settings.audioLanguage, task.phrase);
        task.rows.forEach((phrase) => state.audioCache.set(phrase.id, audio));
        completed += task.rows.length;
        elements.preparationCount.textContent = `${completed}/${preparationTasks.length}`;
        elements.preparationBar.style.width = `${(completed / preparationTasks.length) * 100}%`;
        elements.preparationStatus.textContent = `Preparando audio ${completed} de ${preparationTasks.length}…`;
      }
    };
    await Promise.all(Array.from({ length: Math.min(4, preparationTasks.length) }, worker));
    elements.preparationStatus.textContent = "Cargando los audios de la partida…";
    await preloadSequenceAudios();
    state.preparedSequence = generated.visualSequence;
    state.preparedAudioSequence = generated.audioSequence;
    state.preparedSignature = settingsSignature(settings);
    elements.preparationStatus.textContent = "Audio listo para la partida.";
    elements.startGame.textContent = "Empezar partida →";
    elements.setupError.hidden = true;
  } catch (error) {
    state.preparedSignature = null;
    state.preparedSequence = null;
    state.preparedAudioSequence = null;
    elements.setupError.hidden = false;
    elements.setupError.textContent = `${error.message} Comprueba que has iniciado server.py.`;
    elements.audioPreparation.hidden = true;
    state.audioCache = new Map();
  } finally {
    state.preparing = false;
    setSetupControlsDisabled(false);
    elements.startGame.disabled = false;
  }
}

function validatePool() {
  const pool = filteredPool();
  if (pool.length < 8) {
    elements.setupError.hidden = false;
    elements.setupError.textContent = "No hay suficientes frases disponibles para preparar la sesión.";
    return false;
  }
  elements.setupError.hidden = true;
  return true;
}

function updateCatalogLabel() {
  const pool = filteredPool();
  elements.catalogCount.textContent = `${pool.length} frases disponibles`;
  elements.startGame.disabled = !pool.length || state.preparing;
}

async function loadCatalog() {
  const response = await fetch("data/phrases.json", { cache: "no-store" });
  if (!response.ok) throw new Error("No se pudo cargar el catálogo de frases.");
  state.catalog = await response.json();
  state.pool = [];
  resetPreparedSession();
  updateCatalogLabel();
  checkTtsServer();

  // Show delete button if catalog has subtitle content
  if (state.catalog.length > 0 && state.catalog[0].subtitleName) {
    elements.deleteSubtitles.hidden = false;
  } else {
    elements.deleteSubtitles.hidden = true;
  }
}

elements.interval.addEventListener("input", () => {
  updateIntervalLabel();
  resetPreparedSession();
});
elements.themeToggle.addEventListener("click", () => {
  setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
});
[elements.nBack, elements.rounds, elements.audioLanguage, elements.displayLanguage].forEach((control) => {
  control.addEventListener("change", () => {
    elements.setupError.hidden = true;
    resetPreparedSession();
    updateCatalogLabel();
    if (control === elements.audioLanguage) {
      updateAudioBadge();
      checkTtsServer();
    }
  });
});

elements.setupForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!validatePool()) return;
  const settings = getSettings();
  try {
    if (state.preparedSignature === settingsSignature(settings)) {
      await startGame(settings);
      return;
    }
    await prepareSession(settings);
  } catch (error) {
    elements.setupError.hidden = false;
    elements.setupError.textContent = error.message;
  }
});

elements.answerNo.addEventListener("click", () => registerAnswer(false));
elements.answerYes.addEventListener("click", () => registerAnswer(true));
document.addEventListener("keydown", (event) => {
  if (elements.gameScreen.hidden) return;
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    registerAnswer(false);
  }
  if (event.key === "ArrowRight") {
    event.preventDefault();
    registerAnswer(true);
  }
});

elements.quitGame.addEventListener("click", () => {
  state.gameActive = false;
  clearTurnTimers();
  pausePreparedAudio();
  showScreen(elements.setupScreen);
});
elements.repeatGame.addEventListener("click", async () => {
  try {
    const settings = state.settings;
    showScreen(elements.setupScreen);
    await prepareSession(settings);
    if (state.preparedSignature === settingsSignature(settings)) {
      await startGame(settings);
    }
  } catch (error) {
    elements.setupError.hidden = false;
    elements.setupError.textContent = error.message;
    showScreen(elements.setupScreen);
  }
});
elements.backToSetup.addEventListener("click", () => showScreen(elements.setupScreen));
elements.clearHistory.addEventListener("click", () => {
  if (!readHistory().length || !window.confirm("¿Borrar todas las estadísticas históricas?")) return;
  localStorage.removeItem(HISTORY_STORAGE_KEY);
  renderHistoricalStats();
});
async function testSelectedVoice(language, voiceSelect, button) {
  const phrase = state.pool[0] || state.catalog[0];
  if (!phrase) {
    elements.setupError.hidden = false;
    elements.setupError.textContent = "No hay frases disponibles para probar la voz.";
    return;
  }
  button.disabled = true;
  elements.setupError.hidden = true;
  try {
    const text = language === "en" ? phrase.en : phrase.es;
    const response = await fetch("/api/tts/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        language,
        voice: voiceSelect.value,
      }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || "No se pudo generar el audio de prueba.");
    const audio = new Audio(result.url);
    audio.preload = "auto";
    await preloadAudio(audio);
    await playPreparedAudio(audio);
    elements.voiceStatus.textContent = `Voz ${language === "en" ? "inglesa" : "española"} reproducida.`;
  } catch (error) {
    elements.setupError.hidden = false;
    elements.setupError.textContent = `${error.message} Comprueba que has iniciado server.py.`;
  } finally {
    button.disabled = false;
  }
}

elements.testVoiceEnglish.addEventListener("click", () => testSelectedVoice("en", elements.voiceEnglish, elements.testVoiceEnglish));
elements.testVoiceSpanish.addEventListener("click", () => testSelectedVoice("es", elements.voiceSpanish, elements.testVoiceSpanish));

elements.deleteSubtitles.addEventListener("click", async () => {
  if (!window.confirm("¿Estás seguro de que quieres eliminar los subtítulos procesados y todos sus audios?")) return;

  elements.deleteSubtitles.disabled = true;
  elements.setupError.hidden = true;

  try {
    const response = await fetch("/api/cleanup", { method: "POST" });
    if (!response.ok) throw new Error("No se pudieron eliminar los archivos.");

    // Clear catalog and update UI
    state.catalog = [];
    state.pool = [];
    state.audioCache = new Map();
    state.preparedSignature = null;
    state.preparedSequence = null;
    state.preparedAudioSequence = null;
    state.audioUnlocked = false;
    state.audioUnlockPromise = null;
    updateCatalogLabel();
    elements.deleteSubtitles.hidden = true;
    elements.voiceStatus.textContent = "Voz natural lista para preparar la sesión.";
  } catch (error) {
    elements.setupError.hidden = false;
    elements.setupError.textContent = `${error.message} Comprueba que has iniciado server.py.`;
  } finally {
    elements.deleteSubtitles.disabled = false;
  }
});

elements.processSubtitles.addEventListener("click", async () => {
  const subtitleFilter = elements.subtitleSelect.value;
  if (!subtitleFilter) {
    elements.setupError.hidden = false;
    elements.setupError.textContent = "Selecciona un archivo de subtítulos";
    elements.processSubtitles.disabled = false;
    return;
  }

  // Calculate max phrases based on rounds and n-back
  const rounds = Number(elements.rounds.value);
  const nBack = Number(elements.nBack.value);
  const maxPhrases = rounds + nBack + 50; // Extra buffer for distractors

  elements.processSubtitles.disabled = true;
  elements.startGame.disabled = true;
  elements.setupError.hidden = true;
  elements.subtitleProcessing.hidden = false;
  elements.subtitleStatus.textContent = "Conectando con el servidor…";
  elements.subtitleCount.textContent = "0/0";
  elements.subtitleBar.style.width = "0%";

  try {
    const params = new URLSearchParams({
      subtitle: subtitleFilter,
      max_phrases: String(maxPhrases),
      voice_en: elements.voiceEnglish.value,
      voice_es: elements.voiceSpanish.value,
    });
    const eventSource = new EventSource(`/api/subtitles/process?${params.toString()}`);

    eventSource.addEventListener("progress", (event) => {
      const data = JSON.parse(event.data);
      elements.subtitleStatus.textContent = data.message;
      elements.subtitleBar.style.width = `${data.progress}%`;
      if (data.current && data.total) {
        elements.subtitleCount.textContent = `${data.current}/${data.total}`;
      }
      if (data.subtitle) {
        elements.subtitleStatus.textContent += ` (${data.subtitle})`;
      }
    });

    eventSource.addEventListener("complete", async (event) => {
      const data = JSON.parse(event.data);
      eventSource.close();
      elements.subtitleStatus.textContent = data.message;
      elements.subtitleBar.style.width = "100%";
      elements.subtitleCount.textContent = `${data.phrasesCount}/${data.phrasesCount}`;

      try {
        await loadCatalog();
      } catch (error) {
        elements.setupError.hidden = false;
        elements.setupError.textContent = error.message;
      } finally {
        elements.subtitleProcessing.hidden = true;
        elements.processSubtitles.disabled = false;
        elements.startGame.disabled = false;
      }
    });

    eventSource.addEventListener("error", (event) => {
      const data = event.data ? JSON.parse(event.data) : {};
      eventSource.close();
      elements.setupError.hidden = false;
      elements.setupError.textContent = data.error || "Error procesando subtítulos";
      elements.subtitleProcessing.hidden = true;
      elements.processSubtitles.disabled = false;
      elements.startGame.disabled = false;
    });

    eventSource.onerror = () => {
      eventSource.close();
      elements.setupError.hidden = false;
      elements.setupError.textContent = "Error de conexión con el servidor";
      elements.subtitleProcessing.hidden = true;
      elements.processSubtitles.disabled = false;
      elements.startGame.disabled = false;
    };
  } catch (error) {
    elements.setupError.hidden = false;
    elements.setupError.textContent = `${error.message} Comprueba que has iniciado server.py y tienes las dependencias instaladas.`;
    elements.subtitleProcessing.hidden = true;
    elements.processSubtitles.disabled = false;
    elements.startGame.disabled = false;
  }
});
async function loadSubtitleList() {
  try {
    const response = await fetch("/api/subtitles/list");
    const data = await response.json();
    elements.subtitleSelect.innerHTML = "";
    if (data.subtitles && data.subtitles.length > 0) {
      data.subtitles.forEach((subtitle) => {
        const option = document.createElement("option");
        option.value = subtitle;
        option.textContent = subtitle;
        elements.subtitleSelect.appendChild(option);
      });
    } else {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No hay archivos .srt en subtitles/";
      elements.subtitleSelect.appendChild(option);
    }
  } catch (error) {
    elements.subtitleSelect.innerHTML = '<option value="">Error cargando subtítulos</option>';
  }
}
updateIntervalLabel();
updateAudioBadge();
renderHistoricalStats();
loadSubtitleList();
Promise.all([loadCatalog(), checkTtsServer(), loadAllVoiceOptions()]).catch((error) => {
  elements.setupError.hidden = false;
  elements.setupError.textContent = `${error.message} Ejecuta la aplicación desde un servidor local.`;
  elements.catalogCount.textContent = "Catálogo no disponible";
});
