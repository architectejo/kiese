# Rapport testeur-tresorerie - 2026-11-11

## Vérification BUG-164, volets Trésorerie et Blockchain (relecture de code + `npx tsc --noEmit` : aucune erreur)

Résultat : conforme, sauf deux défauts ouverts, BUG-175 et BUG-176 (voir BUG-172 pour le contrôle `loaded === total` du hook). Le statut de BUG-164 n'est pas modifié (ticket multi-pages).

1. Totaux/KPI : chaque total attend la complétude des listes dont il dépend (`reportsReady`, `dayReady` = rapports ET dépenses, `closuresQ`, `cashbookQ`, `journalQ`, épargne, historique des dépenses). Formules identiques à l'ancien calcul ; totaux serveur affichés sans attente (correct).
2. `consolidatedBalance` : tri serveur `-date,-created_at` avant pagination, donc la page 1 contient l'écriture la plus récente ; `running_balance` est stocké ; aucun re-tri client. Réserve antérieure : la chaîne est globale, un filtre boulangerie/période ne donne pas forcément le solde courant.
3. Clôture : le client n'envoie que les billets, l'écart est calculé par le serveur ; écart affiché masqué tant que les données sont partielles ; `handleConfirmDay` et le bouton de soumission protégés.
4. Impression §5.1.1 et épargne : désactivées jusqu'à complétude, avec garde dans le handler. Contournement relevé : BUG-175.
5. Annulation : `resetKey` inclut période/mois/boulangerie ; réponses obsolètes ignorées. Mélange de boulangeries possible via `extraReports` (BUG-175).
6. Blockchain : vérification calculée serveur sur toute la chaîne ; aperçu `page_size=10` = les plus récentes.
7. Qualité : aucun `any` ajouté, HTTP via `services.ts`.

## Tickets ouverts
- BUG-175 (Majeur, frontend) : `extraReports` jamais vidé.
- BUG-176 (Majeur, backend) : tri `-date` non unique ; risque de ligne sautée entre deux pages.

Limites : aucune exécution navigateur ; contrôle manuel recommandé.

## Vérification BUG-178 (RG/NS exclues du rapport facturier) — VÉRIFIÉ
Détail dans la fiche BUG-178 du registre (bloc « Vérification trésorerie »). Tests : `backend/treasury/tests/test_bug178_verification_2026_11_11.py` (9 verts + 1 expectedFailure BUG-179) ; non-régressions BUG-033/091/100 vertes. Ticket ouvert : BUG-179 (verrou de vacation sur RG, Mineur). Risque noté : rapports historiques d'équipes RG-seules jamais recalculés (réparation de données au déploiement).
