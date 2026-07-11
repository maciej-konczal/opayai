import { generateId } from 'ai'

// AI SDK's ID generator makes every approval and receipt auditable without
// requiring a model key for this mocked hackathon demo.
export const newTransactionId = () => `BOS-${generateId().slice(0, 8).toUpperCase()}`
