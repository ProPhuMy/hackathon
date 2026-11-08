export const SLOT_TO_DEMO_ID = {
  0: '043',
  1: '044',
  2: '045',
  3: '046',
  4: '047',
  5: '048'
};

export function resolveItemBySlot(inventory, slotIndex) {
  const targetId = SLOT_TO_DEMO_ID[slotIndex];
  if (!targetId) return null;
  return inventory.find(item => item.id === targetId) || null;
}
