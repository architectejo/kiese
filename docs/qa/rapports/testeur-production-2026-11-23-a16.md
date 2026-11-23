# Testeur-production a16 (cycle 17, partie A) — 2026-11-23

Fichier : `backend/production/tests/test_verif_production_a16_v16.py` (21 tests : 15 verts, 6 `@expectedFailure`). Log : `$TEMP/a16.log`. Code applicatif non modifié.

## BUG-997 : VÉRIFIÉ (borne), avec 3 résiduels
Vérifié : marqueur honnête stocké après cycle complet ; reçu > borne ou reçu avant confirmation ignoré, lot accepté (200) ; une seule ligne `MIRROR_OUT_OF_BOUNDS` avec `occurrences` incrémentées ; catégorie valide stockée même si une autre est hors borne ; monotonie (marqueur plus bas ne remplace pas, pas de double crédit) ; somme du groupe nulle après résolution siège (ALIGN_ON_SENT avec reçu 105, ALIGN_ON_RECEIVED) sans réinstallation et avec pull dans l'ordre inverse ; rétablissement : le poste reprend la main (marqueur [0,100]).

Résiduels (nouveaux tickets) :
- BUG-1000 (Mineur) : faux positif. Après résolution siège qui réduit la ligne, le poste honnête qui pousse avant de tirer ouvre un conflit `MIRROR_OUT_OF_BOUNDS` (alerte de falsification à tort).
- BUG-1001 (Mineur) : le pull descend le marqueur périmé non borné ; poste réinstallé juste après une résolution : K1 +2 pains fantômes (ALIGN_ON_RECEIVED), K2 -5 (stock négatif, ALIGN_ON_SENT reçu 105).
- BUG-1002 (Mineur) : la borne envoyée d'une demande PENDING est la quantité demandée : K1 pousse [100,0] avant d'avoir vu la demande, n'est jamais débité, somme du groupe 200 au lieu de 100.

Observation sans ticket : la fenêtre de rétablissement (ancien marqueur > borne) permet d'abaisser le marqueur ([0,0]) : un poste hostile propriétaire de son stock peut se faire recréditer. Le cloud ne tient pas le stock des postes, donc limite inhérente (test documenté).

## Balayage fin de partie A
- BUG-1003 (Majeur) : clôture journalière x sync. Envoi la veille, confirmation aujourd'hui : `_apply_pulled_transfers` met à jour le statut de K1 sans `updated_at` ; l'appro effectué de K1 reste classé à hier (journée close, chiffre rétroactif) alors que l'appro reçu de K2 tombe aujourd'hui. Mesuré (K2 aujourd'hui, K1 aujourd'hui, K1 hier) = (100, 0, 100) au lieu de (100, 100, 0).
- Verts : clôture journalière envoi/réception le même jour après sync (+30 000 FC K1, -30 000 FC K2) ; litige entrant bloque la confirmation de la clôture K2 (400) et les ventes (BUG-973) jusqu'au recomptage, litige sortant n'affecte pas K1 ; push de clôture confirmée refusé tant que l'écart persiste ; `BreadDisposal` poussé visible par `?date=` au cloud (jour précédent vide, autre boulangerie 0, date invalide 400) ; push `ConsumableCount` : écart signé, signe inverse, 10^11 et 4 décimales refusés.
- Observation (non ticketée) : le push accepte la création d'un `BreadDisposal` `SOLD_DISCOUNT` que REST refuse depuis BUG-092 (tolérance probable des saisies hors ligne anciennes ; à confirmer par le coordinateur).

## Bilan
Nouveaux tickets : 4 (BUG-1000 à BUG-1003). BUG-997 : à passer à VÉRIFIÉ pour la borne ; les résiduels sont suivis par BUG-1000/1001/1002. Statut de BUG-997 dans le registre non modifié (voir ci-dessous).
