const test = require('node:test');
const assert = require('node:assert/strict');

const ManualState = require('../gui/manual-state.js');
const { attentionReasons, capturePatchBatch, pipelineProgress, renderGate } = ManualState;

test('render gate explains how many transcriptions are still active', () => {
  const gate = renderGate({
    transcription_settled: false,
    approved_count: 2,
    items: [{ state: 'transcribing' }, { state: 'queued' }, { state: 'approved' }],
  });

  assert.deepEqual(gate, { enabled: false, label: 'Ждём транскрибацию: 2' });
});

test('render gate allows one batch action for approved files', () => {
  const gate = renderGate({
    transcription_settled: true,
    approved_count: 7,
    items: [{ state: 'approved' }],
  });

  assert.deepEqual(gate, { enabled: true, label: 'Рендер одобренных (7)' });
});

test('low confidence is attention but not a blocking validation error', () => {
  const reasons = attentionReasons({
    words: [
      { word: ' хорошо', probability: 0.9, deleted: false },
      { word: ' неясно', probability: 0.42, deleted: false },
    ],
  });

  assert.deepEqual(reasons, ['Низкая уверенность: 1 слово']);
});

test('autosave batch keeps the item selected when editing began', () => {
  const batch = capturePatchBatch('item-a', [{ op: 'replace', word_id: 'w1', text: ' правка' }]);
  const currentlySelectedLater = 'item-b';

  assert.equal(batch.itemId, 'item-a');
  assert.notEqual(batch.itemId, currentlySelectedLater);
  assert.equal(batch.operations[0].word_id, 'w1');
});

test('auto pipeline progress remains monotonic across stage resets', () => {
  let progress = 0;
  progress = pipelineProgress(progress, 'transcribing', 100);
  const afterTranscription = progress;
  progress = pipelineProgress(progress, 'preparing', 0);
  const afterPreparing = progress;
  progress = pipelineProgress(progress, 'building', 50);
  const afterBuilding = progress;
  progress = pipelineProgress(progress, 'rendering', 10);

  assert.equal(afterTranscription, 45);
  assert.ok(afterPreparing >= afterTranscription);
  assert.ok(afterBuilding >= afterPreparing);
  assert.ok(progress >= afterBuilding);
  assert.ok(progress < 100);
});

// ---------- single-list workspace ----------

const item = (id, state, extra) => Object.assign({ item_id: id, state, revision: null, name: id + ".mp4" }, extra || {});

test('a video added after a render is offered for transcription, not a stale render gate', () => {
  const snapshot = { items: [item('a', 'completed', { revision: 1 }), item('b', 'pending')] };
  const actions = ManualState.workspaceActions(snapshot, 'b');

  assert.equal(actions.transcribe.enabled, true);
  assert.deepEqual(actions.transcribe.ids, ['b']);
  assert.equal(actions.transcribe.label, 'Transcribe');
  assert.equal(actions.render.enabled, false);
});

test('render picks every file with ready text and needs no approval', () => {
  const snapshot = { items: [
    item('a', 'transcribed', { revision: 1 }), item('b', 'needs_review', { revision: 3 }),
    item('c', 'pending'), item('d', 'completed', { revision: 1 }),
  ] };
  const actions = ManualState.workspaceActions(snapshot, 'a');

  assert.deepEqual(actions.render.ids, ['a', 'b']);
  assert.equal(actions.render.label, 'Render (2)');
  assert.equal(actions.transcribe.label, 'Transcribe');
});

test('with nothing new, render re-renders the selected finished file', () => {
  const snapshot = { items: [item('a', 'completed', { revision: 1 }), item('b', 'completed', { revision: 1 })] };
  const actions = ManualState.workspaceActions(snapshot, 'b');

  assert.deepEqual(actions.render.ids, ['b']);
  assert.equal(actions.render.label, 'Render again');
  assert.equal(actions.render.enabled, true);
});

test('both buttons wait while anything is being processed', () => {
  const snapshot = { items: [item('a', 'transcribing'), item('b', 'pending'), item('c', 'transcribed', { revision: 1 })] };
  const actions = ManualState.workspaceActions(snapshot, 'a');

  assert.equal(actions.busy, true);
  assert.equal(actions.transcribe.enabled, false);
  assert.equal(actions.render.enabled, false);
});

test('files with no speech are not re-queued by Transcribe', () => {
  const actions = ManualState.workspaceActions({ items: [item('a', 'no_speech', { revision: 1 })] }, 'a');
  assert.equal(actions.transcribe.enabled, false);
});

test('timing problems mirror the backend render check', () => {
  const transcript = { duration: 3, words: [
    { id: 'ok', start: 0.1, end: 0.5 },
    { id: 'overlap', start: 0.4, end: 0.8 },
    { id: 'reversed', start: 1.2, end: 1.0 },
    { id: 'gone', start: 0.0, end: 0.1, deleted: true },
    { id: 'late', start: 2.9, end: 3.4 },
  ] };
  assert.deepEqual(Object.keys(ManualState.timingProblems(transcript)), ['overlap', 'reversed', 'late']);
});

test('the word under the playhead is found for the preview', () => {
  const transcript = { words: [
    { id: 'a', start: 0.5, end: 0.9 }, { id: 'b', start: 1.0, end: 1.4 }, { id: 'c', start: 2.0, end: 2.3 },
  ] };
  assert.equal(ManualState.wordAt(transcript, 0.2), null);
  assert.equal(ManualState.wordAt(transcript, 1.1).id, 'b');
  assert.equal(ManualState.wordAt(transcript, 1.7).id, 'b');

  const win = ManualState.previewWindow({ words: ['один', 'два', 'три', 'четыре', 'пять', 'шесть', 'семь']
    .map((word, i) => ({ id: 'w' + i, word: ' ' + word, start: i, end: i + 0.5 })) }, 'w4', 5);
  assert.deepEqual(win.words, ['три', 'четыре', 'пять', 'шесть', 'семь']);
  assert.equal(win.words[win.active], 'пять');
});

test('low-confidence notice uses the right Russian plural', () => {
  const words = (n) => ({ words: Array.from({ length: n }, (_, i) => ({ id: 'w' + i, word: 'x', probability: 0.2 })) });
  assert.deepEqual(ManualState.attentionReasons(words(2)), ['Низкая уверенность: 2 слова']);
  assert.deepEqual(ManualState.attentionReasons(words(5)), ['Низкая уверенность: 5 слов']);
  assert.deepEqual(ManualState.attentionReasons(words(21)), ['Низкая уверенность: 21 слово']);
});

test('with sentence breaks the preview stays inside one sentence and hides periods', () => {
  const transcript = { words: [' основной', ' кухни.', ' Тут', ' нужно', ' пояснить.', ' Это']
    .map((word, i) => ({ id: 'w' + i, word, start: i, end: i + 0.5 })) };

  const plain = ManualState.previewWindow(transcript, 'w2', 5, false);
  assert.deepEqual(plain.words, ['кухни.', 'Тут', 'нужно', 'пояснить.', 'Это']);

  const split = ManualState.previewWindow(transcript, 'w2', 5, true);
  assert.deepEqual(split.words, ['Тут', 'нужно', 'пояснить']);
  assert.equal(split.words[split.active], 'Тут');

  const first = ManualState.previewWindow(transcript, 'w1', 5, true);
  assert.deepEqual(first.words, ['основной', 'кухни']);
  assert.equal(first.words[first.active], 'кухни');
});

test('word mode strips punctuation and quotes but keeps inner hyphens and decimals', () => {
  assert.deepEqual(['«Особые', 'заказчика».', 'какой-то,', '3.5.', '(да)', '—', "don't!"].map(ManualState.cleanWord),
    ['Особые', 'заказчика', 'какой-то', '3.5', 'да', '', "don't"]);
});

test('preview captions follow the renderer grouping in every mode', () => {
  const words = 'Рубрика «Особые пожелания от заказчика». Он говорит, ребята, нужно'.split(' ')
    .map((word, i) => ({ id: 'w' + i, word: ' ' + word, start: i, end: i + 0.5 }));
  const fitsTwo = (texts) => texts.length <= 2;
  const hanging = ManualState.makeIsHanging(['от']);
  const text = (mode) => ManualState.buildCaptions(words, mode, fitsTwo, hanging)
    .map((c) => c.words.map((w) => w.text.trim()).join(' '));

  assert.deepEqual(text('phrases'), ['Рубрика «Особые', 'пожелания', 'от заказчика».', 'Он говорит,', 'ребята, нужно']);
  assert.deepEqual(text('sentences'), ['Рубрика «Особые', 'пожелания', 'от заказчика»', 'Он говорит,', 'ребята, нужно']);
  assert.deepEqual(text('words'), ['Рубрика', 'Особые', 'пожелания', 'от', 'заказчика', 'Он', 'говорит', 'ребята', 'нужно']);
});

test('caption mode falls back to the older sentence_breaks flag', () => {
  assert.equal(ManualState.captionModeOf({}), 'phrases');
  assert.equal(ManualState.captionModeOf({ sentence_breaks: true }), 'sentences');
  assert.equal(ManualState.captionModeOf({ caption_mode: 'words', sentence_breaks: true }), 'words');
});
