import test from 'node:test';
import assert from 'node:assert/strict';
import { moveLibraryBook, libraryDropTarget } from '../src/libraryOrder.js';
const books = ['a', 'b', 'c', 'd'].map((id) => ({ id, progressPercent: 42 }));
test('cross-row moves preserve metadata, input and missing identifiers', () => {
  assert.deepEqual(moveLibraryBook(books, 'a', 'd').map((book) => book.id), ['b', 'c', 'a', 'd']);
  assert.deepEqual(moveLibraryBook(books, 'd', 'a').map((book) => book.id), ['d', 'a', 'b', 'c']);
  assert.equal(moveLibraryBook(books, 'a', 'missing'), books);
  assert.equal(moveLibraryBook(books, 'missing', null), books);
  assert.equal(moveLibraryBook(books, 'a', 'a'), books);
  assert.equal(moveLibraryBook(books, 'a', null)[3].progressPercent, 42);
  assert.deepEqual(books.map((book) => book.id), ['a', 'b', 'c', 'd']);
});
test('drop targets skip dragged item and support appending', () => {
  assert.equal(libraryDropTarget(books, 'b', 'a', true), 'c');
  assert.equal(libraryDropTarget(books, 'a', 'd', true), null);
  assert.equal(libraryDropTarget(books, 'd', 'a', false), 'a');
  assert.equal(libraryDropTarget(books, 'a', 'missing', true), undefined);
});
