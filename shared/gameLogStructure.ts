// shared/gameLogStructure.ts placeholder
export function getEventIcon(eventType: string): string {
  const icons: Record<string, string> = {
    'move': '🚶',
    'shoot': '🎯', 
    'charge': '⚡',
    'combat': '⚔️',
    'wait': '⏸️',
    'error': '❌',
    'default': '📝'
  };
  return icons[eventType] || icons.default;
}

export function getEventTypeClass(eventType: string): string {
  const classes: Record<string, string> = {
    'move': 'text-blue-400',
    'shoot': 'text-red-400',
    'charge': 'text-yellow-400', 
    'combat': 'text-purple-400',
    'wait': 'text-gray-400',
    'error': 'text-red-600',
    'default': 'text-white'
  };
  return classes[eventType] || classes.default;
}