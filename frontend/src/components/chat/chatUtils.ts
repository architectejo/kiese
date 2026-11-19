import axios from 'axios';
import { getErrorDetail } from '@/api/errors';
import type { ChatConversation, ChatUser } from '@/api/services';

export const CHAT_MAX_LENGTH = 2000;
export const CHAT_POLL_MS = 8000;

/** Message d'erreur en français ; le 429 (anti-flood) a un texte dédié. */
export function chatErrorMessage(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err) && err.response?.status === 429) {
    return 'Vous envoyez trop de messages à la suite. Patientez quelques secondes avant de réessayer.';
  }
  return getErrorDetail(err, fallback);
}

export function isForbidden(err: unknown): boolean {
  return axios.isAxiosError(err) && err.response?.status === 403;
}

export function formatChatTime(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay
    ? d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' }) + ' '
      + d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
}

export function conversationTitle(c: ChatConversation): string {
  return c.other_user?.name || c.title || 'Conversation';
}

export function userSubtitle(u: ChatUser): string {
  return [u.role_label, u.node_code].filter(Boolean).join(' · ');
}
