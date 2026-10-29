import '@testing-library/jest-dom'
import { beforeAll } from 'vitest'
import { initMessages } from './shared/messages'

// Screens take their wording from the message bundle; load it once for every test file.
beforeAll(async () => { await initMessages('en') })
