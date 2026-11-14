# Rapport auditeur-comptable — rapprochement Excel août 2026 (2026-11-14)

Périmètre : commissions (CM, retenues, net à payer, remise, report), ventes/BP, `daily_summary`, rapport journalier de clôture, clôture de caisse, livre de caisse. Lecture seule du code applicatif ; aucun test ajouté au dépôt. Aucune donnée réelle copiée : seuls des agrégats figurent ici.

## 1. Méthode

- Lecture des classeurs `DOC 1-2-x` (FACTURATION et synthèse), `D1-3`, `D1-4` avec `openpyxl` (copie en mémoire, scripts hors dépôt).
- Rejeu par l'API REST (`force_authenticate`) dans une **base SQLite isolée** (hors `backend/db.sqlite3`) : K1 et K6 du 1 au 16/08 (16 jours), K5 du 28/07 au 16/08 (20 jours), ~2 900 factures. Clients fictifs (`K1-<n>`), plafond de crédit relevé pour isoler les calculs, `taux = 0` avec commande > 0 rejoué en VENTE SOLDE, ligne sans commande rejouée en remboursement BP.
- Les classeurs ne couvrent que le 1-16/08 : **pas de mois complet** à rejouer.
- Limites : reste du jour/hier par catégorie et écart à la relève non rejoués (pas de stock par catégorie dans les classeurs) ; seule l'identité Excel `reste du hier(d) = - reste du jour(d-1)` a été vérifiée (8/8 boulangeries, 0 écart), elle correspond à la convention BUG-118/135.

## 2. Tableau de rapprochement (agrégats)

| Contrôle | K1 | K6 | K5 | Résultat |
|---|---|---|---|---|
| Jours rejoués | 16 | 16 | 20 | |
| Valeur commandée par jour (`bread_summary`) | 16/16 | 16/16 | 20/20 | identique |
| Cash par jour (`daily_summary`) | 16/16 | 16/16 | 20/20 | identique (hors lignes à paiement négatif, voir BUG-290) |
| CREDIT par jour (`daily_summary`) | 16/16 | 15/16 | 13/20 | écarts = lignes à paiement négatif refusées |
| FACTURE/JR, COMMISSION/JR, VENTE SOLDE (rapport de clôture) | 16/16 | 16/16 | 20/20 | identique |
| ECART/FACTURE (rapport de clôture) | 16/16 | 15/16 | 13/20 | mêmes lignes négatives |
| Commande par client (mois) | 0 écart | 0 écart | 0 écart | identique |
| CM par client (mois) | 0 écart, 3 708 375 | 0 écart, 3 725 750 | 0 écart, 2 849 875 (août seul) | identique |
| Retenue dette (BP) par client | 1 client (-2 000, BP créditrice) | 1 client (-500) | 50 clients (période, BUG-294) | voir BUG-293, BUG-294 |
| Net à payer total (clients comparés) | app 919 291 / Excel 1 171 375 | app 976 692 / Excel 1 326 450 | app -1 011 124 / Excel 1 333 875 | écart = social + CARTE + BP créditrice (K1 : 213 000 + 37 084 + 2 000) |
| Caisse nette cumulée (clôtures 16 jours) | 13 481 500 = Σ paiements Excel | | | identique |
| Livre de caisse (16 entrées chaînées) | solde = précédent + entrée - sortie ; `integrity_check` valide | | | conforme |

Rappel Excel interne : CM = commande × taux (0 écart sur 8 boulangeries), NET = CM - BP (0 écart sur 8), commande = Σ(pains × prix) sauf VENTE SOLDE à 75 % (aucun arrondi : 150/225/375/750), synthèses = FACTURATION pour K1, K6 ; écart pour K2/B2 (bloc de date double), K3/K4/K5/B1 (jours de juillet repris).

## 3. Classement des différences

| # | Différence | Classe | Ticket |
|---|---|---|---|
| 1 | Rapport de clôture journalier rangé à `invoice_date`, autres vues à `delivered_at` | Erreur de l'application | BUG-286 |
| 2 | RG comptée dans le CREDIT de `daily_summary` | Erreur de l'application (contradiction avec la vérif. BUG-275 à lever) | BUG-287 |
| 3 | Crédit du rapport facturier : manquant de VENTE SOLDE, plafonnement par facture | Erreur de l'application | BUG-288 |
| 4 | Cotisation sociale 3 000 FC par défaut ; Excel 0 (B2 2 000) | Règle métier manquante (adaptes.md [3.3]) | BUG-289 |
| 5 | Paiements négatifs de l'Excel non saisissables | Cas non spécifié | BUG-290 |
| 6 | CARTE 1 % déduite, vide dans l'Excel | Contradiction CLAUDE.md §5.3 / adaptes.md [3.2] | BUG-291 |
| 7 | REMISE 0,1 % de la CM (app, adaptes.md) contre 0,25 % de la commande (Excel) | Documentation inexacte / règle à confirmer | BUG-292 |
| 8 | BP créditrice ignorée (app) ou ajoutée (Excel) | Cas non spécifié | BUG-293 |
| 9 | Période de paie Excel déborde sur juillet ; bloc de date double K2/B2 | Anomalie Excel + règle à confirmer | BUG-294 |
| 10 | Remise annuelle `pains × 0,025` ; cahier contre adaptes.md | Contradiction de documents | BUG-295 |
| 11 | ECART/FACTURE inclut les remboursements, commentaire contraire | Cas non spécifié | BUG-296 |
| 12 | Livre D1-3 : CA ≠ Σ paiements FACTURATION ; D1-4 : une rupture de solde (-6 000 FC, ligne 450) | Erreur ou écart de l'Excel | Q-016 |

Ordre de priorité des documents : les points 4, 6, 7, 10 mettent en jeu adaptes.md contre CLAUDE.md / cahier ; non tranchés, voir `docs/qa/QUESTIONS_CLIENT.md` Q-009 à Q-016.

## 4. Points conformes

- BP cumulative, solde `BP_après = BP_avant + commande - paiement` (aucun écart sur les 52 jours client).
- CM = 25 % ; VENTE SOLDE à 75 % sans CM ; formule NET = CM - BP - retenues alignée sur l'Excel quand social, CARTE et BP créditrice sont neutralisés.
- `daily_summary` : décote de VENTE SOLDE hors CREDIT ; clé `delivered_at` : facture créée le 20, livrée le 21 comptée le 21 (K/B2).
- Clôture de caisse : caisse nette = ventes cash - dépenses ; billetage en 8 coupures ; livre : chaîne SHA-256 valide.

## 5. Incident : base `backend/db.sqlite3` touchée par erreur (à décider par l'équipe)

Mon premier script a positionné `DB_NAME`, mais `settings.py` charge `.env` avec `load_dotenv(override=True)` : la variable a été écrasée et deux exécutions courtes ont écrit dans `backend/db.sqlite3` (le rejeu suivant utilise un module de réglages dédié et un chemin vérifié par assertion ; `db.sqlite3` n'a plus été touchée). Résidus :
- migration `core.0019_user_must_change_password` appliquée (heure 13:03 UTC, était en attente) ;
- 8 lignes `core_breadprice` (id 5 à 12, libellés « Pain 200/300/500/1000 », doublons) ;
- utilisateur `aud_dir` (rôle DIRECTION, mot de passe jetable) ;
- `core_config.allow_backdated_sales` passé à 1 (valeur d'origine inconnue, très probablement 0, défaut du modèle) ;
- 11 lignes `core_activitylog` datées 13:03-13:04 UTC (config, formats de pain, agent).
Le nettoyage ciblé a été refusé par le système d'autorisation : il reste à faire par un responsable (suppression des ids 5-12 de `core_breadprice`, de `aud_dir`, remise de `allow_backdated_sales` à 0, suppression des 11 logs). Aucune facture ni aucun client ajouté. Recommandation : lancer toute exécution sur copie de la base ou rendre `load_dotenv` non écrasant (`override=False`) pour que `DB_NAME` fonctionne.

## 6. Contradictions entre documents à arbitrer

- CLAUDE.md §5.3 (retenues = dette + sociale + imprimés + autre) contre adaptes.md [3.2] (CARTE 1 %) : BUG-291.
- Cahier des charges §2.3.3 contre adaptes.md [4.2] pour la remise annuelle : BUG-295.
- adaptes.md [3.2] « REMISE ≈ 0,1 % du CM » contre formules réelles des classeurs : BUG-292.
- BUG-275 (clé `delivered_at`) contre génération des périodes de paie par `invoice_date` : BUG-286.
- CLAUDE.md §5.2 (BP jamais remise à zéro) : l'Excel redémarre à 0 à chaque période (aucun report visible dans les feuilles d'août) ; l'app est conforme à CLAUDE.md.

## 7. Fichiers

- Registre : `d:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (BUG-286 à BUG-296).
- Questions : `d:\Projects\kiesse\docs\qa\QUESTIONS_CLIENT.md` (Q-009 à Q-016).
- Scripts de rejeu (hors dépôt, lisent les classeurs à l'exécution) : dossier temporaire de session, `replay.py`, `compare.py`, `closure_cmp.py`, `targeted.py`, `cash.py`.
