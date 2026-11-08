import assert from 'node:assert';
import {
  nameFor,
  kindFor,
  mapInventory,
  mapEvent,
} from '../../src/liveData.js';

function runTests() {
  const roster = [
    { person_id: 'p1', name: 'Alice', enrollment_status: 'ENROLLED' },
    { person_id: 'p2', name: 'Bob', enrollment_status: 'PENDING' },
  ];

  // 1. nameFor: null, known, and unknown ids
  assert.strictEqual(nameFor(null, roster), 'Unknown');
  assert.strictEqual(nameFor(undefined, roster), 'Unknown');
  assert.strictEqual(nameFor('p1', roster), 'Alice');
  assert.strictEqual(nameFor('p2', roster), 'Bob');
  assert.strictEqual(nameFor('p_unknown', roster), 'p_unknown');

  // 2. kindFor:
  // 'milk carton' -> carton, 'food container' -> box, 'can' -> bottle, 'fruit' -> fruit, 'hand' -> placeholder
  assert.strictEqual(kindFor('milk carton'), 'carton');
  assert.strictEqual(kindFor('food container'), 'box');
  assert.strictEqual(kindFor('can'), 'bottle');
  assert.strictEqual(kindFor('fruit'), 'fruit');
  assert.strictEqual(kindFor('hand'), 'placeholder');

  // 3. mapInventory:
  // - with two cartons gives slots 0 and 5
  // - a third carton gets the first free other slot (1)
  // - a placeholder item gets slot undefined
  // - seven non-placeholder items leave the seventh undefined
  // - output sorted by since_ts
  const testRows = [
    { item_id: 'it7', item_label: 'fresh fruit', owner_id: 'p1', since_ts: '2026-03-01T10:07:00Z' },
    { item_id: 'it1', item_label: 'oat milk', owner_id: 'p1', since_ts: '2026-03-01T10:01:00Z' },
    { item_id: 'it4', item_label: 'hand', owner_id: 'p2', since_ts: '2026-03-01T10:04:00Z' },
    { item_id: 'it3', item_label: 'soy carton', owner_id: 'p1', since_ts: '2026-03-01T10:03:00Z' },
    { item_id: 'it2', item_label: 'orange juice', owner_id: 'p2', since_ts: '2026-03-01T10:02:00Z' },
    { item_id: 'it5', item_label: 'food container', owner_id: 'p2', since_ts: '2026-03-01T10:05:00Z' },
    { item_id: 'it6', item_label: 'yogurt jar', owner_id: 'p1', since_ts: '2026-03-01T10:06:00Z' },
    { item_id: 'it8', item_label: 'soda can', owner_id: 'p2', since_ts: '2026-03-01T10:08:00Z' },
  ];

  const mapped = mapInventory(testRows, roster);

  // Assert sorted by since_ts ascending
  for (let i = 0; i < mapped.length - 1; i++) {
    const tCurrent = new Date(testRows.find((r) => r.item_id === mapped[i].id).since_ts).getTime();
    const tNext = new Date(testRows.find((r) => r.item_id === mapped[i + 1].id).since_ts).getTime();
    assert.ok(tCurrent <= tNext, 'Items must be sorted by since_ts ascending');
  }

  // 1st carton (it1: oat milk) -> slot 0
  assert.strictEqual(mapped[0].id, 'it1');
  assert.strictEqual(mapped[0].slot, 0);

  // 2nd carton (it2: orange juice) -> slot 5
  assert.strictEqual(mapped[1].id, 'it2');
  assert.strictEqual(mapped[1].slot, 5);

  // 3rd carton (it3: soy carton) -> first free other slot (1)
  assert.strictEqual(mapped[2].id, 'it3');
  assert.strictEqual(mapped[2].slot, 1);

  // Placeholder item (it4: hand) -> slot undefined, placeholder: true
  assert.strictEqual(mapped[3].id, 'it4');
  assert.strictEqual(mapped[3].slot, undefined);
  assert.strictEqual(mapped[3].placeholder, true);

  // Remaining non-placeholder items:
  // it5 (food container, box) -> preferred 1 taken, next free is 2
  assert.strictEqual(mapped[4].id, 'it5');
  assert.strictEqual(mapped[4].slot, 2);

  // it6 (yogurt jar, jar) -> preferred 2 taken, next free is 3
  assert.strictEqual(mapped[5].id, 'it6');
  assert.strictEqual(mapped[5].slot, 3);

  // it7 (fresh fruit, fruit) -> preferred 4 is free -> slot 4
  assert.strictEqual(mapped[6].id, 'it7');
  assert.strictEqual(mapped[6].slot, 4);

  // it8 (soda can, bottle) -> 7th non-placeholder item, slots 0..5 all taken -> undefined
  assert.strictEqual(mapped[7].id, 'it8');
  assert.strictEqual(mapped[7].slot, undefined);

  // 4. mapEvent:
  // status mapping for all three statuses and confidence 0.8282 -> '83%'
  const baseEvent = {
    event_id: 'ev-1',
    topic: 'fridge.event',
    type: 'PUT',
    item_id: 'it1',
    item_label: 'oat milk',
    person_id: 'p1',
    owner_id: 'p1',
    ts: '2026-03-01T12:00:00Z',
    confidence: 0.8282,
    status: 'ok',
  };

  const mappedOk = mapEvent(baseEvent, roster);
  assert.strictEqual(mappedOk.id, 'ev-1');
  assert.strictEqual(mappedOk.result, 'Verified');
  assert.strictEqual(mappedOk.confidence, '83%');
  assert.strictEqual(mappedOk.item, 'Oat milk');
  assert.strictEqual(mappedOk.person, 'Alice');
  assert.strictEqual(mappedOk.owner, 'Alice');

  const mappedMismatch = mapEvent(
    { ...baseEvent, event_id: 'ev-2', status: 'wrong_owner', person_id: 'p2' },
    roster
  );
  assert.strictEqual(mappedMismatch.result, 'Mismatch');
  assert.strictEqual(mappedMismatch.person, 'Bob');

  const mappedUncertain = mapEvent(
    { ...baseEvent, event_id: 'ev-3', status: 'uncertain', person_id: null },
    roster
  );
  assert.strictEqual(mappedUncertain.result, 'Uncertain');
  assert.strictEqual(mappedUncertain.person, 'Unknown');

  console.log('✅ PASS: live data checks passed successfully.');
}

runTests();
