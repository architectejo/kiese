import { test } from '@playwright/test';

/**
 * Parcours 10 — Journée complète (CLAUDE.md §2 point 10) : enchaîne les
 * parcours 3 à 8 (clients → facturation → livraison → production →
 * clôture → livre de caisse) sur une même boulangerie, de bout en bout.
 *
 * Reporté dans cette session : chaque brique (04 à 08) est déjà testée
 * individuellement, mais le chaînage réaliste bout-en-bout (même journée
 * calendaire, mêmes vacations équipe A/B, rapport Niveau 1 non vide,
 * clôture Niveau 2 confirmée par un COMPTABLE distinct du GERANT, puis
 * versement au Livre de Caisse par la Direction) suppose un scénario
 * sur plusieurs comptes coordonnés et un volume de données qui n'a pas pu
 * être construit et stabilisé dans le temps disponible de cette session
 * (contention de ressources signalée par le coordinateur en cours de
 * session). Les blocages connus en amont (06-tresorerie-caisse.spec.ts,
 * tests "clôture gérant" et "versement... Livre de Caisse") sont la même
 * cause racine : il faut d'abord un historique de facturation/livraison
 * réaliste sur la journée pour que le rapport Niveau 1 ne soit pas vide.
 *
 * Prochaine étape recommandée (voir rapport testeur-e2e-2026-10-22.md) :
 * écrire un script de seed dédié (`manage.py shell`, données DEMO) qui crée
 * directement, pour un nœud et une date donnés, des factures DELIVERED sur
 * les deux équipes avec des montants connus — pour que ce test puisse
 * démarrer directement à l'étape clôture sans dépendre du minutage temps
 * réel de l'UI (un rapport Niveau 1 porte sur "aujourd'hui").
 */

test.fixme('journée complète : clients → facturation → production → clôture → livre de caisse (une boulangerie)', async () => {
  // Non implémenté dans cette session — voir note ci-dessus et le rapport.
});
