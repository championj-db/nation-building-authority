import { describe, expect, test } from 'vitest';
import { linePath, linePoints, multiLinePath } from './geo';

const line = [[133.197, -25.999], [133.299, -25.842]];

describe('geometry helpers', () => {
  test('accept JSON text and already-parsed arrays (AppKit parses JSON-shaped strings)', () => {
    expect(multiLinePath(JSON.stringify([line]))).toBe(multiLinePath([line]));
    expect(linePath(JSON.stringify(line))).toBe(linePath(line));
    expect(multiLinePath([line])).toMatch(/^M[\d.]+ [\d.]+L[\d.]+ [\d.]+$/);
  });

  test('tolerate empty or malformed input', () => {
    expect(multiLinePath(null)).toBe('');
    expect(multiLinePath('not json')).toBe('');
    expect(linePoints([['x', 1]])).toEqual([]);
  });
});

import { isTrue } from './rows';

describe('isTrue', () => {
  test('treats the transport string "false" as false', () => {
    expect([isTrue(true), isTrue('true'), isTrue(false), isTrue('false'), isTrue(null), isTrue('')]).toEqual([true, true, false, false, false, false]);
  });
});
