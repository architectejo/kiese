# Testeur Clients/Commissions b12 (2026-11-23)

Fichier : `backend/clients/tests/test_clients_v9.py` (36 tests : 32 verts, 4 `@expectedFailure`).

## Vérification BUG-941 à 950 : tous VÉRIFIÉS
Push d'identité (champs appliqués, dette/BP/pains/code/is_active jamais touchés, champ invalide = rejet global, garde `updated_at`, catégorie et notification de risque), pull (plafond + identité, catégorie cohérente, valeurs invalides ignorées), PATCH partiel vs livraison concurrente (séquence simulée), journal et notifications, année cotisation 2000-2200, is_paid/paid_at, PATCH node (cotisation et client, code régénéré), amount=0.

## Nouveaux tickets : 4
- BUG-951 (Majeur) : la garde `updated_at` du push ignore une édition d'identité légitime dès qu'un mouvement de dette d'un autre poste a fait avancer `updated_at` du Cloud (perte silencieuse, ACCEPTED).
- BUG-952 (Majeur) : le pull écrase plafond/identité d'une édition locale non encore poussée (`is_synced=False`).
- BUG-953 (Mineur, À CLARIFIER) : cotisation d'une distribution clôturée modifiable (PATCH et toggle_paid).
- BUG-954 (Mineur) : PATCH `is_paid` et DELETE de cotisation non journalisés.

## Avis BUG-947 (PATCH direct de is_paid)
Acceptable : `paid_at` est désormais cohérent (posé, conservé, vidé) et aucune règle de gel n'existe pour les cotisations (BUG-263/889 visent les commissions payées/périodes clôturées). Le vrai écart est le gel après clôture de distribution (953) et l'absence de trace (954).

## Constats non ticketés
Garde `updated_at` appliquée après validation (champ invalide rejeté même daté ancien : correct) ; `bulk_create_month` borne l'année à 2100 alors que le sérialiseur accepte 2200 ; `is_active` non propagé par le push.
