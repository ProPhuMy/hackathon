import assert from 'node:assert';
import { resolveItemBySlot, SLOT_TO_DEMO_ID } from '../../src/itemMapping.js';

const mockInventory = [
  { id: '043', name: 'Oat milk', owner: 'Viet' },
  { id: '044', name: 'Lunch box', owner: 'Khang' },
  { id: '045', name: 'Greek yogurt', owner: 'Phong' },
  { id: '046', name: 'Cold brew', owner: 'Dang' },
  { id: '047', name: 'Apples', owner: 'Khang' },
  { id: '048', name: 'Orange juice', owner: 'Viet' },
];

function runTests() {
  // Test 1: Normal resolution
  const expectedIDs = ['043', '044', '045', '046', '047', '048'];
  expectedIDs.forEach((expectedId, slotIndex) => {
    assert.strictEqual(SLOT_TO_DEMO_ID[slotIndex], expectedId);
    assert.strictEqual(resolveItemBySlot(mockInventory, slotIndex)?.id, expectedId);
  });


  // Test 2: Reordered inventory must not change item
  const reordered = [...mockInventory].reverse();
  assert.strictEqual(resolveItemBySlot(reordered, 0).id, '043');
  assert.strictEqual(resolveItemBySlot(reordered, 5).id, '048');

  // Test 3: Missing records must not crash or open a different item
  const missing = mockInventory.filter(i => i.id !== '044');
  assert.strictEqual(resolveItemBySlot(missing, 1), null);

  // Test 4: Unknown slots
  assert.strictEqual(resolveItemBySlot(mockInventory, 99), null);

  // Test 5: Extra/unmapped items are ignored by mapping
  const extra = [...mockInventory, { id: '099', name: 'Cake' }];
  assert.strictEqual(resolveItemBySlot(extra, 0).id, '043');
  
  console.log('✅ Mapping tests passed.');
}

runTests();
