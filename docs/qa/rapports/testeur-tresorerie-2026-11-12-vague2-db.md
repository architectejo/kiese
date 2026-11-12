# Rapport testeur-tresorerie — vague 2 sur la base réelle (K3) — 2026-11-12

Périmètre : module Trésorerie et Clôture. API réelle `http://localhost:8000` (base `backend/db.sqlite3` restaurée : 678 clients, aucune facture, livre vide au départ), UI `http://localhost:5173/treasury` (Playwright, 360 px et 1366 px). Boulangerie K3 uniquement ; comptes `@pierre`, `@gerant-k3`, comptes fictifs `zz_treso_*`. Aucune écriture SQL, aucun `migrate`/`flush`/reset, aucun git, aucune modification du code applicatif ; la rotation de K3 était déjà activée à l'état initial (non modifiée). Charge machine très élevée pendant toute la session (appels API de 5 à 20 s, Vite intermittent).

## 1. Ce qui a été exécuté

### (A) Re-vérification des tickets corrigés (reproduction exacte, base réelle)
| Ticket | Résultat |
|---|---|
| BUG-200 | Gérant : `validate`/`reject`/`push_to_cashbook` -> 403 ; facturier/livreur `validate` -> 403 ; comptable et direction confirment, infirment (le gérant resoumet), versent ; le gérant voit sa clôture (retrieve + liste) ; chaîne valide après 4 versements du siège, `integrity_check` = `run_check` = `global_status`. **VÉRIFIÉ** |
| BUG-201 | `bills_10000=99999999999`, `bills_20000=100001`, négatif, texte, décimal -> 400 (POST et PATCH), aucune ligne créée ; liste, `suggested_ca`, journal CA lisibles ; bordereau et comptage direction démesurés -> 400. **VÉRIFIÉ** |
| BUG-202 | Journal : PATCH/PUT/DELETE -> 405 (gérant, facturier, direction) ; POST facturier/livreur -> 403 ; montants négatifs -> 400 ; solde progressif exact. **VÉRIFIÉ** |
| BUG-203 | Totaux ignorés en PATCH ; rapport validé : PATCH/PUT 400, DELETE 403, `generate` le laisse validé. **VÉRIFIÉ** |
| BUG-204 | Deux corrections rétroactives : `CORR-K3-20261109-01` et `-02` (19 car., distinctes), soldes 29 700 / 30 300. **VÉRIFIÉ** |
| BUG-205 | -500, 0, `abc` -> 400. **VÉRIFIÉ** |
| BUG-206 | Bornes (revenu, taux, sacs) -> 400 ; facturier/livreur 403 en écriture ; `?node=` sans fuite pour le gérant (le filtre `node` de django-filter réduit à l'intersection vide) ; direction `?node=` correct. **VÉRIFIÉ** |
| BUG-207 | `period_summary` en chaînes décimales. **VÉRIFIÉ** (défaut voisin : BUG-241). |
| BUG-231 | **Partiellement vérifié** (voir §4) : laissé `CORRIGÉ`. |

### (B) Non-régression vague 1
Rapports par équipe (A/B = 10 200 cash / 6 000 crédit, égaux aux factures ; facturier/livreur refusés), caisse nette 20 400 - 2 500 = 17 900, billetage 18 000 (écart +100), 11-09 : écart négatif -200 puis recalcul automatique après vente tardive (12 000 / 11 200 / -1 200), écart nul 11 200 (test auto), billets invalides 400, double clôture 400 (gérant et direction), PATCH/PUT clôture confirmée 400, DELETE gérant et direction 403 (BUG-198), versements `VC-K3-20261110`, `-0109`, `-0108`, `-0107` (soldes progressifs, ordre de chaînage par `chain_seq` malgré dates désordonnées, BUG-199), double versement 400, API livre POST/PUT/PATCH/DELETE 405, lecture refusée au gérant, filtre de date et `period_summary`, journal CA / sorties, confrontation, comptage direction (17 900, écart 0). Parcours normal intact : le gérant crée et resoumet sa clôture, le comptable/direction confirme et verse.

### (C) Nouveau
- **Altération directe** (sur COPIE de la base réelle dans un dossier temporaire, source ouverte en lecture seule, copie supprimée) : montant modifié en SQL -> détecté (4 écritures signalées : l'écriture et les suivantes) par `integrity_check`, `run_check` et `global_status` (même verdict) ; après restauration, `is_tampered` reste posé et l'alerte reste ouverte ; **suppression de la dernière écriture non détectée** (BUG-240) ; `previous_hash` seul non vérifié (BUG-238, test auto).
- **Intégrité à 30 écritures** (test automatisé) : chaîne valide, solde = cumul, détection par les deux endpoints pour altération de : montant, solde, `node`, `imputation`, libellé, pièce, date, `is_correction`, échange de `chain_seq`, suppression intermédiaire.
- **Bordereaux de décaissement** : sur la base réelle uniquement les refus (gérant 403, billetage démesuré 400, 20 000 > solde 17 900 -> 400, aucune écriture créée), car un bordereau écrit dans le livre global sous le nœud SIEGE ; effet sur le solde, solde exact, final_report et chaîne : tests automatisés (BUG-239 : bordereau à 0 FC accepté).
- **Transfert en litige** (K4 -> K3, 2 pains, reçu 1) : création de clôture K3 bloquée (400, message en français avec le détail), versement d'une clôture déjà confirmée bloqué (400), récepteur ne peut pas résoudre (403), motif obligatoire (400), résolution par l'émetteur K4 -> `CONFIRMED`, clôture et versements de nouveau possibles ; un transfert annulé ne bloque pas (test auto).
- **Fenêtre minuit-01:00** (tests automatisés, heure simulée 23:30 UTC = 00:30 locale) : sans rotation, rapport daté du jour local 2026-11-13 ; en rotation, rapport rattaché à la journée de travail 2026-11-12 ; clôture de cette journée = même cash.
- **Export / impression** : aucun endpoint d'export côté trésorerie ; l'impression est côté client (`window.print()` dans `Treasury.tsx`, bordereau final) : non exercée (popups non automatisés dans l'environnement saturé).
- **UI** : voir §4.

## 2. Données de test créées (base réelle `db.sqlite3`, K3)

Comptes : `zz_treso_facturier_a` (K3, A), `zz_treso_facturier_b` (K3, B), `zz_treso_livreur` (K3), `zz_treso_comptable` (sans nœud), mot de passe = identifiant. Clients : `ZZTEST Treso 1/2/3` (K3-0068 à K3-0070). Factures K3 livrées : 2026-11-10 (20), 2026-11-09 (8 + 3 tardives). Rapports 11-10 (A validé, B) et 11-09 (A, B). Dépenses : 11-10 (1 500, 700, 300), 11-09 (800). Clôtures K3 : 11-10, 11-09, 11-08, 11-07, toutes confirmées et versées (une clôture du jour 2026-11-12 créée puis supprimée par le gérant). Journal K3 2026-11-10 : CA 20 400, PAY_BLG 1 000, EAU 250,50. Épargne K3 2026-11-10 (2 sacs, 20 400 FC, 10 % = 2 040). Comptage direction 2026-11-10 (17 900, écart 0). Transfert K4 -> K3 (2 x Pain 200 FC, litige puis `ALIGN_ON_SENT`) : stock K4 -2 et K3 +2 de cette catégorie. Instantanés `BlockchainSnapshot` et notifications générés par `run_check` et les clôtures.

**Écritures du livre de caisse direction (toutes K3, chaînage par rang d'insertion)**

| Rang | Date | Pièce | Entrée | Sortie | Solde |
|---|---|---|---|---|---|
| 1 | 2026-11-10 | `VC-K3-20261110` | 17 900 | 0 | 17 900 |
| 2 | 2026-11-09 | `VC-K3-20261109` | 11 200 | 0 | 29 100 |
| 3 | 2026-11-12 | `CORR-K3-20261109-01` (correction) | 600 | 0 | 29 700 |
| 4 | 2026-11-12 | `CORR-K3-20261109-02` (correction) | 600 | 0 | 30 300 |
| 5 | 2026-11-08 | `VC-K3-20261108` | 0 | 0 | 30 300 |
| 6 | 2026-11-07 | `VC-K3-20261107` | 0 | 0 | 30 300 |

Solde final 30 300 FC ; chaîne intègre (les deux endpoints).

**Incident à signaler** : une ligne de mon script de scénario (transfert) a créé par erreur une clôture **K1 du 2026-11-08** (id `1f467160-c868-430b-8bb9-2793705cb767`, vide, non confirmée, créée par `@gerant-k1`). La suppression (DELETE par le gérant K1) a été refusée par l'environnement ; elle reste à supprimer par le gérant K1 ou la direction (suppression autorisée tant que non confirmée). Aucune autre donnée hors K3 modifiée, hors le transfert K4 -> K3 ci-dessus.

## 3. Tickets

- **VÉRIFIÉS** : BUG-200, 201, 202, 203, 204, 205, 206, 207 (registre mis à jour).
- **Ouverts** (tests `@expectedFailure` dans `backend/treasury/tests/test_vague2_db_testeur_tresorerie.py`) : BUG-238 (Mineur, `previous_hash` stocké non vérifié), BUG-239 (Mineur, bordereau à 0 FC), BUG-240 (**Majeur**, suppression directe de la dernière écriture non détectée), BUG-241 (Mineur, `monthly_total` épargne en flottants), BUG-242 (Mineur, route `/treasury` ouverte aux FACTURIER/LIVREUR, frontend).
- Suite : `python manage.py test treasury.tests.test_vague2_db_testeur_tresorerie` -> 30 tests, OK, 4 échecs attendus (238, 239, 240, 241).
- Observations non ouvertes : un versement de net 0 crée une écriture 0/0 ; la liste du livre est triée par date décroissante alors que le solde suit l'ordre d'insertion ; `POST /closures/` exige `date`.

## 4. UI (Playwright)

- 360 px et 1366 px, gérant K3, comptable et direction : aucun débordement horizontal (scrollWidth = largeur), aucune erreur console ni réponse API >= 400 ; la liste « Clôtures du Jour » s'affiche.
- Boutons : le gérant ne voit ni Confirmer, ni Infirmer, ni Inscrire au Livre de Caisse (le seul « Confirmer » détecté est « Confirmer l'équipe B », autre module) ; le comptable voit la mention « Cliquez pour confirmer / infirmer » ; la section bordereaux et le livre sont affichés aux rôles siège uniquement.
- Facturier (accès direct à l'URL) : voir BUG-242.
- Non rejoué faute de réponse de Vite sous charge : affichage des erreurs serveur du billetage et clic sur Confirmer/Inscrire dans le détail ; BUG-231 reste donc `CORRIGÉ` (vérification complète à reprendre).
