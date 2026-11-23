# Testeur trésorerie, ronde c14 (2026-11-23)

Fichier : `backend/treasury/tests/test_verif_tresorerie_c14_v13.py` (33 tests : 28 verts, 5 `@expectedFailure`). Log : `$TEMP/c14.log`.

## Vérifiés
- BUG-971 : un push de clôture crée toujours une clôture non confirmée (avec ou sans `is_validated=True`) ; seul REST IsHeadquarters (direction, comptable) confirme, le gérant reçoit 403. Flux 2 postes + cloud : validation REST puis versement REST, pièce `VC-C1-AAAAMMJJ`, double versement refusé, chaîne et deux endpoints d'intégrité cohérents. Rejeu après validation : montants, statut et livre inchangés. Clôture infirmée : un rejeu validé ne la confirme pas. Les 7 tests adaptés testent toujours l'essentiel (rejeu sans doublon, montants figés, pièce et chaîne) ; la partie « versement » passe par validation REST ou simulée par update ORM.
- BUG-969 : conflit `IDENTITE_OBSOLETE` + notification, pas de bruit sur rejeu identique, consultable par direction, comptable et admin (403 gérant, facturier, livreur).
- BUG-970 : le payload porte `updated_at` et `identity_updated_at` ; push ancien ignoré et tracé, push récent appliqué, poste sans version appliqué, repli sur `updated_at`, versions invalides sans 500.
- BUG-972 : premier gagne dans un lot, autre lot peut corriger, code dupliqué refusé et tracé ; billets `'4'`, `'4 '`, `' 4'`, `'04'`, `4`, `0`, vide, null acceptés ; `'+4'`, `'2.0'`, `'1e3'`, -1, `'-1'`, True, 4.0, non ASCII, `'4_0'`, `'0x4'`, énormes refusés (clôture et bordereau).

## Nouveaux tickets (4)
- BUG-981 (Mineur) : horloge de poste en avance écrase l'édition du siège sans trace (risque annoncé d37 : seul le sens « en retard » est tracé).
- BUG-982 (Mineur) : notification recréée à chaque push obsolète (5 pushs = 1 conflit, 5 notifications).
- BUG-983 (Majeur) : clôture infirmée, resoumission jamais appliquée et pull sans état de clôture (le gérant du poste ne sait pas qu'il doit recompter).
- BUG-984 (Mineur) : BUG-972 (1) contourné par un id en majuscules, sans tirets ou entre accolades.

## Observations (sans ticket)
- Une clôture confirmée par le comptable mais pas encore versée est versée par un simple rejeu du poste (comportement conservé par d36, test `test_observation_...`). À confirmer métier si le versement doit rester un acte distinct.
- REST accepte `'2.0'` pour les billets (DRF), le sync le refuse : écart de strictesse sans conséquence.
- Un stamp de poste égal à la version du Cloud est appliqué (comparaison stricte `<`).
- Stamp futur non bloqué mais sans empoisonnement : la version du Cloud devient l'heure serveur.
- Push d'un modèle hors périmètre (livre, bordereau d'épargne, journal, finance, commissions) : refusé sans 500 ; le pull ne fuit ni livre ni clôtures d'un autre nœud.
