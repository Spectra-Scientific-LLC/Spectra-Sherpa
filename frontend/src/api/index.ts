/**
 * API client exports
 *
 * Provides both named and default exports for flexibility:
 * - import api from '@/api/client' (direct import)
 * - import { api } from '@/api' (barrel export)
 * - import api from '@/api' (default re-export)
 */

import api from './client'

export { api }
export default api
