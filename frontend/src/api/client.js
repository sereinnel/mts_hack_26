/** Единственная точка обращения к существующему FastAPI. Новых маршрутов здесь нет. */
export const DEFAULT_API_URL = 'http://127.0.0.1:8000';
export const API_URL = (typeof window !== 'undefined' && window.ENERGYTOOL_API_URL) || DEFAULT_API_URL;

export class ApiError extends Error {
  constructor(message, status = 0, cause = null) {
    super(message, { cause });
    this.name = 'ApiError';
    this.status = status;
  }
}

const formatDetail = (detail) => {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((item) => item?.msg || String(item)).join('; ');
  return 'Неизвестная ошибка сервера';
};

export async function apiRequest(path, { method = 'GET', body, timeoutMs = 60000, signal } = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  const cancel = () => controller.abort();
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener('abort', cancel, { once: true });
  }
  try {
    const response = await fetch(`${API_URL}${path}`, {
      method,
      headers: { ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      signal: controller.signal,
    });
    let data;
    try { data = await response.json(); } catch { data = null; }
    if (!response.ok) {
      throw new ApiError(formatDetail(data?.detail) || `HTTP ${response.status}`, response.status);
    }
    if (data === null) throw new ApiError('Сервер вернул некорректный ответ.', response.status);
    return data;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (controller.signal.aborted) throw new ApiError('Истекло время ожидания ответа сервера.', 0, err);
    throw new ApiError('Нет соединения с сервером. Проверьте запуск FastAPI.', 0, err);
  } finally {
    clearTimeout(timeout);
    if (signal) signal.removeEventListener('abort', cancel);
  }
}

const sid = (id) => encodeURIComponent(id);
export const api = {
  health: () => apiRequest('/health', { timeoutMs: 6000 }),
  createSession: () => apiRequest('/api/sessions', { method: 'POST' }),
  // GET /api/sessions intentionally not used by public UI: backend has no user authentication.
  listSessions: () => apiRequest('/api/sessions'),
  getMessages: (id) => apiRequest(`/api/sessions/${sid(id)}/messages`),
  closeSession: (id) => apiRequest(`/api/sessions/${sid(id)}/close`, { method: 'POST' }),
  chat: (sessionId, message) => apiRequest('/api/chat', {
    method: 'POST', body: { session_id: sessionId, message }, timeoutMs: 90000,
  }),
  createLead: ({ sessionId, fullName, phone, company, consent }) =>
    apiRequest('/api/leads', {
      method: 'POST',
      body: {
        session_id: sessionId,
        full_name: fullName.trim(),
        phone: phone.trim(),
        company: company.trim(),
        consent_to_contact: consent === true,
      },
    }),
};
