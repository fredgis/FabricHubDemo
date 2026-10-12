import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, it } from 'vitest';

const source = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)),
  '..', '..', 'apps', 'cockpit', 'src', 'assets', 'msflix-dataflow-en.html'));
const document = new DOMParser().parseFromString(source.toString('utf8'), 'text/html');
const inventory = JSON.parse(document.querySelector('#inventory-data')!.textContent!);

it('preserves the exact English HTML supplied for integration, including line endings', () => {
  expect(source.byteLength).toBe(203378);
  expect(createHash('sha256').update(source).digest('hex'))
    .toBe('5524278a4a9f74d997df2f6a248293b0f83f9560e62145ab097e5fb50c6a59d4');
  expect(document.documentElement.lang).toBe('en');
  expect(document.querySelectorAll('script[src], link[rel="stylesheet"], iframe')).toHaveLength(0);
});

it('retains all profiles, tables, processing steps, keys and historical screen mappings', () => {
  expect(inventory.profiles.map((profile: { id: string; tables: unknown[] }) => [profile.id, profile.tables.length])).toEqual([
    ['oracle', 19], ['salesforce', 22], ['sap', 126], ['rti', 22], ['raw', 9],
    ['silver', 35], ['gold', 65], ['ontology', 22], ['cockpit', 38], ['flixy', 30], ['planning', 0],
  ]);
  expect(inventory.profiles.map((profile: { process: unknown[] }) => profile.process.length))
    .toEqual([6, 6, 7, 7, 5, 6, 5, 4, 5, 3, 2]);
  expect(inventory.keys).toHaveLength(6);
  expect(inventory.screens).toHaveLength(9);
});

it('keeps one shared Gold warehouse and all three cockpit input paths', () => {
  const edges = document.querySelectorAll('[data-from][data-to]');
  const nodes = new Set([...edges].flatMap(edge => [edge.getAttribute('data-from'), edge.getAttribute('data-to')]));
  expect(nodes.size).toBe(14);
  expect(edges).toHaveLength(16);
  expect(nodes.has('sap-gold')).toBe(false);
  expect([...edges].filter(edge => edge.getAttribute('data-to') === 'cockpit')
    .map(edge => edge.getAttribute('data-from')).sort()).toEqual(['flixy', 'gold', 'ontology']);
  expect(document.querySelector('[data-from="sap-preparation"][data-to="gold"]')).not.toBeNull();
});
