/** Validate the local RAG evaluation labels without network calls or credentials. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const datasetPath = resolve(root, 'support_tickets/regression_questions.json');
const dataset = JSON.parse(readFileSync(datasetPath, 'utf8'));
const categories = ['direct_factual', 'multi_fact', 'exact_value', 'paraphrase', 'multi_section', 'unanswerable'];
const companies = ['HackerRank', 'Claude', 'Visa'];
const normalize = text => text.replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n');
const hash = text => createHash('sha256').update(text, 'utf8').digest('hex');
const codepoints = text => Array.from(text).length;
const sources = new Map();

assert.equal(dataset.questions.length, 30, 'Expected 30 questions');
assert.equal(dataset.answerability_scope, 'source_document');
assert.equal(new Set(dataset.questions.map(q => q.id)).size, 30, 'Duplicate question IDs');
assert.equal(new Set(dataset.questions.map(q => q.question.toLowerCase().replace(/\s+/g, ' ').trim())).size, 30, 'Duplicate questions');

for (const doc of dataset.source_documents) {
  assert.ok(doc.document_id.startsWith('data/') && !doc.document_id.includes('\\'), 'Use corpus-relative POSIX IDs');
  const path = resolve(root, doc.document_id);
  assert.ok(path.startsWith(resolve(root, 'data') + sep), 'Source escaped the corpus');
  const text = normalize(readFileSync(path, 'utf8'));
  assert.equal(doc.content_sha256, hash(text), `Source changed: ${doc.document_id}`);
  assert.ok(!sources.has(doc.document_id), 'Duplicate document ID');
  sources.set(doc.document_id, text);
}

let quotations = 0;
let answerable = 0;
for (const q of dataset.questions) {
  assert.ok(categories.includes(q.category), `Unknown category: ${q.id}`);
  assert.ok(companies.includes(q.company), `Unknown company: ${q.id}`);
  assert.ok(['easy', 'medium', 'hard'].includes(q.difficulty), `Unknown difficulty: ${q.id}`);
  assert.equal(typeof q.answerable, 'boolean');
  assert.ok(typeof q.question === 'string' && q.question.trim().length > 0);
  const text = sources.get(q.source_document_id);
  assert.ok(text !== undefined, `Missing source: ${q.id}`);
  const sourceFolder = {HackerRank: 'hackerrank', Claude: 'claude', Visa: 'visa'}[q.company];
  assert.ok(q.source_document_id.startsWith(`data/${sourceFolder}/`), `Wrong company source: ${q.id}`);
  if (!q.answerable) {
    assert.equal(q.category, 'unanswerable');
    assert.equal(q.expected_answer, null);
    assert.deepEqual(q.evidence, []);
    assert.deepEqual(q.supporting_facts, []);
    assert.ok(typeof q.missing_information === 'string' && q.missing_information.length > 0);
    continue;
  }
  answerable++;
  assert.notEqual(q.category, 'unanswerable');
  assert.ok(typeof q.expected_answer === 'string' && q.expected_answer.length > 0);
  assert.equal(q.missing_information, null);
  assert.ok(q.supporting_facts.length > 0 && q.supporting_facts.every(f => typeof f === 'string' && f.length > 0));
  assert.ok(q.evidence.length > 0);
  const points = Array.from(text);
  for (const ev of q.evidence) {
    quotations++;
    assert.equal(ev.page, null, 'Markdown documents do not have page numbers');
    assert.ok(Number.isInteger(ev.start_char) && Number.isInteger(ev.end_char));
    assert.ok(ev.start_char >= 0 && ev.end_char > ev.start_char && ev.end_char <= points.length);
    assert.equal(points.slice(ev.start_char, ev.end_char).join(''), ev.quotation, `Quote or span mismatch: ${q.id}`);
    const prefix = points.slice(0, ev.start_char).join('');
    assert.equal(ev.line_start, prefix.split('\n').length, `Line mismatch: ${q.id}`);
    assert.equal(ev.line_end, ev.line_start + ev.quotation.split('\n').length - 1);
    assert.equal(ev.end_char - ev.start_char, codepoints(ev.quotation));
    const headings = ev.section.split(' > ');
    assert.ok(headings.length > 0 && headings.every(h => text.includes(h)), `Missing heading: ${q.id}`);
  }
  if (q.category === 'multi_section') {
    assert.ok(new Set(q.evidence.map(ev => ev.section)).size >= 2, `Need distinct sections: ${q.id}`);
  }
}

const categoryCounts = Object.fromEntries(categories.map(c => [c, dataset.questions.filter(q => q.category === c).length]));
const companyCounts = Object.fromEntries(companies.map(c => [c, dataset.questions.filter(q => q.company === c).length]));
assert.ok(Object.values(categoryCounts).every(n => n === 5), 'Expected five questions per category');
assert.ok(Object.values(companyCounts).every(n => n === 10), 'Expected ten questions per company');
assert.equal(answerable, 25);
assert.deepEqual(new Set(sources.keys()), new Set(dataset.questions.map(q => q.source_document_id)), 'Unused or missing sources');
console.log(JSON.stringify({valid: true, questions: 30, answerable, unanswerable: 30 - answerable, source_documents: sources.size, verified_quotations: quotations, categories: categoryCounts, companies: companyCounts}, null, 2));
