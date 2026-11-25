# Conception : journée comptable de midi à midi (BUG-1130)

Source : réponse FERME du client Q-018 (2026-11-24) : « la journée (clôture, rapport, versement) va de MIDI À MIDI (l'heure de clôture de la boulangerie, 12:00 par défaut) », toutes boulangeries (rotation 24 h, Q-017). Remplace la décision du 2026-11-12 (jour calendaire). Résout les contradictions C2 à C4 de `ANALYSE_ROTATION_A1_2026-11-21.md` (C5 : `cadre_comptable.md` ne connaît pas de clôture intra-journalière, la journée comptable de midi à midi n'y contredit rien).

## 1. Définition

- **Journée comptable D** = de D à l'heure de clôture (`Node.handover_time`, 12:00 par défaut) incluse, à D+1 à la même heure, exclue.
- **Date de journée comptable** = date calendaire locale du DÉBUT de la période. Une vente à D+1 09:00 appartient à la journée D ; à D+1 12:00 pile, à la journée D+1.
- Helper unique, dans `backend/core/workday.py` :
  - `business_day_for(node, instant=None)` : date de journée comptable d'un instant ;
  - `business_day_bounds(node, d)` : (début inclus, fin exclue), datetimes aware ;
  - `closure_time_for(node)` : heure de clôture du nœud, 12:00 si nœud absent (siège) ou valeur invalide ;
  - `work_date_for` (existant, source unique des appelants) délègue à `business_day_for` ; `delivered_on_work_date_filter` devient un filtre par intervalle `[début, fin[` ; `workday_bounds` et `business_date` sont des alias.
  - `instant_in_business_day(node, d, now)` : instant d'une vente rétroactive placé DANS la journée demandée (l'ancien « date + heure courante » retombait dans la journée voisine avant midi).
- Fuseau `Africa/Kinshasa`, sans changement d'heure : aucune ambiguïté de bascule.

## 2. Inventaire des découpages par jour calendaire

| Endroit | État avant | Traitement |
|---|---|---|
| `core/workday.py` (`work_date_for`, `delivered_on_work_date_filter`, `team_at_day_start`) | `.date()` / `__date` | Réécrit autour du helper (lot 1) |
| `treasury/closure_lock.py` (verrou de vente, `closure-status`) | clôture du jour calendaire, « heure atteinte » = 12:00 du jour | La clôture à valider est celle de la journée qui vient de se terminer (D-1 dès la bascule de D) ; bloque tant qu'elle n'est pas validée (lot 2) |
| `treasury` : `daily-closure`, `CashClosure` unique `(node, date)`, versements, dépenses locales, `DailySavings`, rapport facturier (`regenerate_facturier_reports`), `signals` (livraison rétroactive) | `work_date_for` + `delivered_on_work_date_filter` | Suivent le helper sans autre changement (lots 2 et 3) ; date de l'écriture de correction du livre de caisse (`treasury/services.py`) = journée comptable |
| `sales` : `daily_summary` (`delivered_at__date`), `bread_summary`, `invoice_date` par défaut, `_combine_date_with_now_time`, notification « ventes bloquées » (une par jour) | mélange calendaire / helper | `daily_summary` par intervalle et par nœud ; `_combine_date_with_now_time` via `instant_in_business_day` ; la notification est dédupliquée par journée comptable (lot 3) |
| `production` : sessions (`date`), restes du jour (`DailyBreadStockSnapshot`, `BreadDisposal`), `auto_close_day` / `auto_close_due_days`, `shift-end-status` (clôture silencieuse « au passage de minuit »), confirmation de stock de départ, inventaire physique du jour (`inventory_date`) | calendaire dans 4 endroits | `auto_close_day` : la journée D se termine à D+1 12:00 ; « minuit » ne clôture plus rien ; inventaire du jour = journée comptable (lot 4) |
| `production/intrants_stats.py` (mouvements de consommables sans session) | `created_at__date` / `localtime().date()` | Jour = journée comptable du nœud du mouvement (lot 5) |
| `sync/services.py` : contrôles « pas de date future » sur `delivered_at`, `not_served_at`, `closed_at` | date calendaire de l'horodatage comparée à la date de travail | Comparaison avec la journée comptable de l'horodatage (sinon une livraison à D+1 09:00 serait refusée) (lot 5) |
| `commissions` (`invoice_date__month/year`) | suit `invoice_date` | Non modifié : suit la date de journée comptable (voir question Q-1130-A) |
| `clients/views.py` (30 derniers jours, mois d'un relevé), `finance/*` (année), `blockchain` (`snapshot_date`), `production/flour_month_stats.py` (achats siège par mois) | calendaire | NON concernés : agrégats mensuels/annuels ou technique, pas une « journée » de caisse ou de production |
| `Invoice.invoice_date` (`default=timezone.localdate`) | valeur de repli du modèle | Inchangé (migration inutile) : les vues passent toujours `work_date_for(node)`. Une facture créée hors vue (script, test) garde la date calendaire |

## 3. Synchronisation

- `CashClosure.date`, `FacturierReport.date`, `ProductionSession.date`, `DailySavings.date`, `LocalExpense.date`, `Invoice.invoice_date` restent des `DateField` : leur SENS change (journée comptable), pas leur format ni leurs clés (UUID). Unicité `(node, date)` inchangée.
- Risque : un poste local et le cloud doivent appliquer la MÊME version de règle, sinon une vente de 09:00 est rangée sous deux dates et deux clôtures peuvent apparaître pour deux jours « décalés ». À déployer ensemble (cloud puis postes) ; le poste ne devrait pas pousser de clôtures tant qu'il n'est pas à jour.
- Le contrôle de dates futures de la synchronisation compare désormais la journée comptable.

## 4. Migrations de données : recommandation (aucune réécriture)

**Aucun schéma ne change, aucune migration n'est créée.** Recommandation écrite : NE PAS réécrire les dates passées.
- Les lignes historiques gardent leur date calendaire. Seules les ventes entre 00:00 et 12:00 d'un jour D seraient rangées autrement si on les recalculait (jour D-1) ; les clôtures confirmées sont figées et les rapports régénérés pour une date passée utilisent la nouvelle règle.
- Jour de bascule C : à déployer APRÈS la clôture validée de la journée en cours (de préférence à midi). Avant midi le jour C, la journée comptable est C-1 : si la clôture calendaire de C-1 est déjà confirmée, les ventes du matin de C seraient refusées (BUG-988) ou régénéreraient un jour figé. La base ayant été remise à zéro le 2026-11-10, le volume historique à risque est faible.
- Les verrous de vente (`block_sales_after_closure`) sont par défaut désactivés ; à l'activation, la clôture validée de la veille comptable est exigée.

## 5. API (rétrocompatible)

- Aucun champ ajouté ni retiré. Le paramètre `date` (rapports, clôtures, daily_summary, bread_summary, production du jour) désigne la **date de journée comptable**.
- `closure-status` : mêmes clés ; `closure_date` = journée terminée à valider (D-1 après la bascule de D) ; `closure_hour` toujours l'heure de clôture.
- `work-date` renvoyés au frontend (`work_date`, `current_work_date`) = journée comptable. Le frontend ne doit pas recalculer « aujourd'hui » : il utilise ces valeurs (point à relayer à `dev-frontend` si des pages utilisent encore `new Date()`).

## 6. Risques et questions pour le client

- **Q-1130-A** : les commissions et rapports MENSUELS suivent `invoice_date` : une vente du 1er du mois à 09:00 compte dans le mois PRÉCÉDENT (journée du dernier jour). C'est cohérent avec « la journée va de midi à midi » mais à confirmer pour le calcul des commissions de paie.
- **Q-1130-B** : verrou de vente (BUG-973) : bloque dès l'heure de clôture tant que la clôture de la journée terminée n'est pas validée, même s'il n'y a eu aucune vente la veille (comportement identique à l'ancien pour un jour sans vente).
- **Q-1130-C** : changement de l'heure de clôture d'une boulangerie en cours d'année : les jours déjà enregistrés gardent leur date, seuls les nouveaux instants suivent la nouvelle heure (chevauchement ou trou possible le jour du changement). À faire hors journée active.
- Désignation d'équipe hors rotation (`shift_date`) reste calendaire (périmètre de l'autre agent, `team_rotation_enabled`).

Aucun risque de perte ni de duplication de données bloquant n'a été relevé : pas d'arrêt de codage.
